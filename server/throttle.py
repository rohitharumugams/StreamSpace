"""Map wall-clock time → Mbps from a 1 Hz trace file."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ThrottleConfig:
    enabled: bool = False
    trace: str | None = None
    loop: bool = True
    samples_mbps: list[float] = field(default_factory=list)
    started_at: float | None = None

    def reset_clock(self) -> None:
        self.started_at = time.monotonic()

    def current_mbps(self) -> float | None:
        if not self.enabled or not self.samples_mbps:
            return None
        if self.started_at is None:
            self.reset_clock()
        elapsed = time.monotonic() - self.started_at
        index = int(elapsed)
        if index < 0:
            index = 0
        if index >= len(self.samples_mbps):
            if self.loop:
                index %= len(self.samples_mbps)
            else:
                index = len(self.samples_mbps) - 1
        return self.samples_mbps[index]

    def status(self) -> dict:
        mbps = self.current_mbps()
        elapsed = None
        if self.started_at is not None:
            elapsed = round(time.monotonic() - self.started_at, 3)
        return {
            "enabled": self.enabled,
            "trace": self.trace,
            "loop": self.loop,
            "sample_count": len(self.samples_mbps),
            "elapsed_seconds": elapsed,
            "current_mbps": mbps,
        }


def parse_trace_file(path: Path) -> list[float]:
    samples: list[float] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        samples.append(float(line.split()[0]))
    if not samples:
        raise ValueError(f"Trace file has no samples: {path}")
    return samples


throttle = ThrottleConfig()
