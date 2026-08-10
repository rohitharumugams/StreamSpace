"""ABR controllers (Python ports of player/abr.js)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Level:
    name: str
    height: int
    bitrate: int  # bps
    segment_bytes: list[int]


@dataclass
class AbrContext:
    levels: list[Level]
    current_level: int
    buffer_seconds: float
    throughput_bps: float
    segment_duration: float
    throughput_std_bps: float = 0.0
    throughput_trend: float = 0.0  # recent relative change, negative = declining


class AbrController(Protocol):
    name: str

    def decide(self, ctx: AbrContext) -> int: ...


class ThroughputAbr:
    name = "throughput"

    def __init__(self, safety: float = 0.8) -> None:
        self.safety = safety

    def decide(self, ctx: AbrContext) -> int:
        if not ctx.levels:
            return 0
        if ctx.throughput_bps <= 0:
            return max(0, ctx.current_level)
        budget = ctx.throughput_bps * self.safety
        chosen = 0
        for i, level in enumerate(ctx.levels):
            if level.bitrate <= budget:
                chosen = i
        return chosen


class BufferAbr:
    name = "buffer"

    def __init__(self, low: float = 4.0, high: float = 12.0) -> None:
        self.low = low
        self.high = high

    def decide(self, ctx: AbrContext) -> int:
        if not ctx.levels:
            return 0
        level = max(0, ctx.current_level)
        if ctx.buffer_seconds < self.low:
            level = max(0, level - 1)
        elif ctx.buffer_seconds > self.high:
            level = min(len(ctx.levels) - 1, level + 1)
        return level


class HybridAbr:
    name = "hybrid"

    def __init__(
        self,
        safety: float = 0.75,
        low: float = 5.0,
        high: float = 15.0,
        reservoir: float = 8.0,
    ) -> None:
        self.safety = safety
        self.low = low
        self.high = high
        self.reservoir = reservoir
        self._throughput = ThroughputAbr(safety=safety)

    def decide(self, ctx: AbrContext) -> int:
        if not ctx.levels:
            return 0
        level = max(0, ctx.current_level)
        thru = self._throughput.decide(ctx)

        if ctx.buffer_seconds < 2:
            level = 0
        elif ctx.buffer_seconds < self.low:
            level = min(thru, max(0, level - 1))
        elif ctx.buffer_seconds < self.reservoir:
            level = min(level, thru)
        elif ctx.buffer_seconds > self.high:
            level = level + 1 if thru > level else thru
        else:
            level = thru

        return max(0, min(len(ctx.levels) - 1, level))


class RiskAwareAbr:
    """Conservative hybrid that prices in throughput uncertainty.

    Core question: how likely is an underrun before the next segment arrives?
    Uses mean/variance, buffer headroom, and recent trend to shrink the
    affordable bitrate and damp upgrades under volatile regimes.
    """

    name = "risk"

    def __init__(
        self,
        base_safety: float = 0.8,
        low_buffer: float = 5.0,
        high_buffer: float = 14.0,
        risk_horizon: float = 1.15,
    ) -> None:
        self.base_safety = base_safety
        self.low_buffer = low_buffer
        self.high_buffer = high_buffer
        self.risk_horizon = risk_horizon
        self._hold = 0  # segments to wait before another upgrade

    def _volatility(self, ctx: AbrContext) -> float:
        if ctx.throughput_bps <= 0:
            return 1.0
        return max(0.0, ctx.throughput_std_bps / ctx.throughput_bps)

    def _conservative_bps(self, ctx: AbrContext, cv: float) -> float:
        mean = ctx.throughput_bps
        if mean <= 0:
            return 0.0
        std = ctx.throughput_std_bps
        z = 0.4 + 1.2 * min(cv, 1.0)
        if ctx.buffer_seconds < self.low_buffer:
            z += 0.5
        if ctx.throughput_trend < -0.15:
            z += 0.4
        floor = mean * (0.35 if cv > 0.5 else 0.45)
        return max(mean - z * std, floor)

    def _safety(self, ctx: AbrContext, cv: float) -> float:
        safety = self.base_safety
        if cv > 0.5:
            safety = 0.55
        elif cv > 0.3:
            safety = 0.65
        elif cv > 0.15:
            safety = 0.72
        if ctx.buffer_seconds < 3:
            safety *= 0.7
        elif ctx.buffer_seconds < self.low_buffer:
            safety *= 0.85
        elif ctx.buffer_seconds > self.high_buffer and cv < 0.2:
            safety = min(0.9, safety + 0.08)
        return safety

    def _underrun_risk(
        self,
        bitrate: float,
        conservative_bps: float,
        buffer_s: float,
        seg_s: float,
    ) -> float:
        if conservative_bps <= 0:
            return 10.0
        est_download = (bitrate * seg_s) / conservative_bps
        return est_download / max(buffer_s, 0.05)

    def _target_level(self, ctx: AbrContext, cv: float) -> int:
        conservative = self._conservative_bps(ctx, cv)
        budget = conservative * self._safety(ctx, cv)
        chosen = 0
        for i, level in enumerate(ctx.levels):
            if level.bitrate > budget:
                break
            risk = self._underrun_risk(
                level.bitrate,
                conservative,
                ctx.buffer_seconds,
                ctx.segment_duration,
            )
            limit = self.risk_horizon if ctx.buffer_seconds >= self.low_buffer else 0.9
            if risk <= limit:
                chosen = i
        return chosen

    def decide(self, ctx: AbrContext) -> int:
        if not ctx.levels:
            return 0
        current = max(0, ctx.current_level)
        if ctx.throughput_bps <= 0:
            return current

        cv = self._volatility(ctx)
        target = self._target_level(ctx, cv)

        # Emergency / low-buffer: only move down, never thrash upward.
        if ctx.buffer_seconds < 2:
            self._hold = 2
            return 0
        if ctx.buffer_seconds < self.low_buffer:
            self._hold = max(self._hold, 1)
            return min(target, current, max(0, current - 1))

        # Prefer stability: keep current if it is still affordable.
        conservative = self._conservative_bps(ctx, cv)
        current_bitrate = ctx.levels[current].bitrate
        current_risk = self._underrun_risk(
            current_bitrate,
            conservative,
            ctx.buffer_seconds,
            ctx.segment_duration,
        )
        safety = self._safety(ctx, cv)
        affordable = current_bitrate <= conservative * safety * 1.05
        safe_enough = current_risk <= self.risk_horizon * (1.15 if cv > 0.35 else 1.35)

        if target < current:
            # Only step down when current is meaningfully unsafe.
            if affordable and safe_enough and ctx.buffer_seconds >= self.low_buffer:
                if self._hold > 0:
                    self._hold -= 1
                return current
            if current_bitrate > conservative * safety * 1.35:
                chosen = max(target, current - 2)
            else:
                chosen = current - 1
            self._hold = 2
            return max(0, chosen)

        if target > current and affordable and safe_enough:
            # Upgrade only with healthy buffer, mild volatility, and no downtrend.
            can_up = (
                ctx.buffer_seconds >= 10.0
                and ctx.throughput_trend >= -0.1
                and self._hold <= 0
                and current_risk <= 0.95
            )
            if cv > 0.55:
                can_up = can_up and ctx.buffer_seconds >= self.high_buffer
            if can_up:
                self._hold = 2 if cv < 0.3 else 4
                return min(len(ctx.levels) - 1, current + 1)
            if self._hold > 0:
                self._hold -= 1
            return current

        if self._hold > 0:
            self._hold -= 1
        return current


class FixedAbr:
    name = "fixed"

    def __init__(self, level: int = 0, label: str | None = None) -> None:
        self.level = level
        if label:
            self.name = label

    def decide(self, ctx: AbrContext) -> int:
        if not ctx.levels:
            return 0
        return max(0, min(len(ctx.levels) - 1, self.level))


def create_abr(name: str, fixed_level: int = 0) -> AbrController:
    if name == "throughput":
        return ThroughputAbr()
    if name == "buffer":
        return BufferAbr()
    if name == "hybrid":
        return HybridAbr()
    if name in {"risk", "risk-aware"}:
        return RiskAwareAbr()
    if name == "fixed":
        return FixedAbr(fixed_level, label=f"fixed-{fixed_level}")
    if name == "fixed-low":
        return FixedAbr(0, label="fixed-low")
    if name == "fixed-high":
        return FixedAbr(10_000, label="fixed-high")
    raise ValueError(
        "Unknown ABR '{0}'. Choose from: throughput, buffer, hybrid, risk, "
        "fixed, fixed-low, fixed-high".format(name)
    )
