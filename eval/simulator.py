"""Trace-driven ABR playback simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from eval.abr import AbrContext, AbrController, Level
from eval.catalog import bandwidth_at


@dataclass
class SimConfig:
    ewma_alpha: float = 0.3
    max_buffer_s: float = 30.0
    loop_trace: bool = True


@dataclass
class SegmentRecord:
    index: int
    level: int
    quality: str
    bytes: int
    download_s: float
    throughput_bps: float
    buffer_before_s: float
    buffer_after_s: float
    rebuffer_s: float
    wall_time_s: float


@dataclass
class SimResult:
    video: str
    abr: str
    trace: str
    segment_count: int
    duration_s: float
    startup_latency_s: float
    total_rebuffer_s: float
    rebuffer_events: int
    quality_switches: int
    avg_bitrate_kbps: float
    avg_buffer_s: float
    bandwidth_utilization: float
    time_avg_bitrate_kbps: float
    segments: list[SegmentRecord] = field(default_factory=list)

    def summary(self) -> dict:
        data = asdict(self)
        data.pop("segments")
        return data


def simulate(
    *,
    video: str,
    abr: AbrController,
    levels: list[Level],
    segment_duration: float,
    trace_mbps: list[float],
    trace_name: str,
    config: SimConfig | None = None,
) -> SimResult:
    cfg = config or SimConfig()
    n = len(levels[0].segment_bytes)

    buffer_s = 0.0
    wall_t = 0.0
    ewma_bps = 0.0
    recent_samples: list[float] = []
    level = 0
    last_level = None
    switches = 0
    rebuffer_events = 0
    total_rebuffer = 0.0
    startup_latency = 0.0
    bitrate_sum = 0.0
    buffer_sum = 0.0
    bytes_downloaded = 0
    records: list[SegmentRecord] = []

    def stats_from_recent() -> tuple[float, float, float]:
        if not recent_samples:
            return ewma_bps, 0.0, 0.0
        mean = sum(recent_samples) / len(recent_samples)
        if len(recent_samples) == 1:
            return ewma_bps or mean, 0.0, 0.0
        var = sum((x - mean) ** 2 for x in recent_samples) / (len(recent_samples) - 1)
        std = var**0.5
        half = max(1, len(recent_samples) // 2)
        older = sum(recent_samples[:half]) / half
        newer = sum(recent_samples[-half:]) / half
        trend = ((newer - older) / older) if older > 0 else 0.0
        return ewma_bps or mean, std, trend

    for i in range(n):
        mean_bps, std_bps, trend = stats_from_recent()
        ctx = AbrContext(
            levels=levels,
            current_level=level,
            buffer_seconds=buffer_s,
            throughput_bps=mean_bps,
            segment_duration=segment_duration,
            throughput_std_bps=std_bps,
            throughput_trend=trend,
        )
        level = abr.decide(ctx)
        if last_level is not None and level != last_level:
            switches += 1
        last_level = level

        seg_bytes = levels[level].segment_bytes[i]
        # Integrate over the download using the time-varying trace.
        remaining = float(seg_bytes)
        download_s = 0.0
        downloaded = 0.0
        while remaining > 0:
            mbps = bandwidth_at(trace_mbps, wall_t + download_s, loop=cfg.loop_trace)
            bytes_per_s = max(mbps, 0.05) * 1_000_000 / 8.0
            # Stay within the current 1-second trace bucket.
            bucket_left = 1.0 - ((wall_t + download_s) % 1.0)
            step = min(remaining / bytes_per_s, bucket_left if bucket_left > 1e-9 else 1.0)
            step = max(step, 1e-6)
            got = bytes_per_s * step
            if got > remaining:
                step = remaining / bytes_per_s
                got = remaining
            remaining -= got
            downloaded += got
            download_s += step

        sample_bps = (seg_bytes * 8.0) / download_s if download_s > 0 else 0.0
        ewma_bps = (
            sample_bps
            if ewma_bps <= 0
            else cfg.ewma_alpha * sample_bps + (1 - cfg.ewma_alpha) * ewma_bps
        )
        recent_samples.append(sample_bps)
        if len(recent_samples) > 8:
            recent_samples.pop(0)

        buffer_before = buffer_s
        rebuffer_s = 0.0

        # During download, the playhead drains the buffer.
        if i == 0:
            # Startup: nothing plays until first segment arrives.
            startup_latency = download_s
            wall_t += download_s
            buffer_s = segment_duration
        else:
            if download_s <= buffer_s:
                buffer_s -= download_s
                wall_t += download_s
            else:
                # Buffer underrun while waiting for the segment.
                rebuffer_s = download_s - buffer_s
                total_rebuffer += rebuffer_s
                rebuffer_events += 1
                wall_t += download_s
                buffer_s = 0.0
            buffer_s = min(cfg.max_buffer_s, buffer_s + segment_duration)

        bytes_downloaded += seg_bytes
        bitrate_sum += levels[level].bitrate
        buffer_sum += buffer_s

        records.append(
            SegmentRecord(
                index=i,
                level=level,
                quality=levels[level].name,
                bytes=seg_bytes,
                download_s=round(download_s, 4),
                throughput_bps=round(sample_bps, 1),
                buffer_before_s=round(buffer_before, 3),
                buffer_after_s=round(buffer_s, 3),
                rebuffer_s=round(rebuffer_s, 4),
                wall_time_s=round(wall_t, 3),
            )
        )

    play_duration = n * segment_duration
    # Approx total available bits over session wall clock from the trace.
    session_s = wall_t
    offered_bits = 0.0
    t = 0.0
    while t < session_s:
        mbps = bandwidth_at(trace_mbps, t, loop=cfg.loop_trace)
        dt = min(1.0 - (t % 1.0), session_s - t)
        offered_bits += mbps * 1_000_000 * dt
        t += dt
    utilization = (bytes_downloaded * 8.0) / offered_bits if offered_bits > 0 else 0.0

    return SimResult(
        video=video,
        abr=abr.name,
        trace=trace_name,
        segment_count=n,
        duration_s=play_duration,
        startup_latency_s=round(startup_latency, 4),
        total_rebuffer_s=round(total_rebuffer, 4),
        rebuffer_events=rebuffer_events,
        quality_switches=switches,
        avg_bitrate_kbps=round((bitrate_sum / n) / 1000.0, 2),
        avg_buffer_s=round(buffer_sum / n, 3),
        bandwidth_utilization=round(utilization, 4),
        time_avg_bitrate_kbps=round((bitrate_sum / n) / 1000.0, 2),
        segments=records,
    )
