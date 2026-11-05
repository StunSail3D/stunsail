"""Power estimation and energy integration from raw status samples.

Method: heater `power` is a 0-1 duty fraction (a control signal, not watts). DC load is
rated watts x duty, plus linear fan loads and a base load. DC load is converted to wall
input through the PSU efficiency at that load, then external AC loads are added once.
Energy is integrated with the trapezoidal rule between consecutive samples. Intervals
longer than `max_gap_s`, or touching an invalid sample, are NOT integrated or
interpolated; they are reported as uncovered time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .profile import CalibrationProfile

JOULES_PER_KWH = 3_600_000.0
DEFAULT_MAX_GAP_S = 5.0


@dataclass(frozen=True)
class PowerEstimate:
    dc_w: float
    wall_w: float
    psu_efficiency: float
    components_w: dict[str, float]


@dataclass(frozen=True)
class EnergyInterval:
    start: datetime
    end: datetime
    kwh: float


@dataclass
class EnergyResult:
    kwh: float
    covered_s: float
    uncovered_s: float
    invalid_samples: int
    intervals: list[EnergyInterval] = field(default_factory=list)
    profile_name: str = ""
    profile_version: int = 0
    basis: str = "estimated"

    @property
    def coverage(self) -> float:
        total = self.covered_s + self.uncovered_s
        return self.covered_s / total if total else 0.0

    @property
    def average_w(self) -> float:
        return self.kwh * JOULES_PER_KWH / self.covered_s if self.covered_s else 0.0


def _number(group: Any, key: str) -> float | None:
    value = group.get(key) if isinstance(group, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _duty(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def estimate_power(status: dict[str, Any], profile: CalibrationProfile) -> PowerEstimate | None:
    """Return None when a required heater reading is missing or not numeric."""
    bed = _number(status.get(profile.bed_object), "power")
    hotend = _number(status.get(profile.hotend_object), "power")
    if bed is None or hotend is None:
        return None
    components = {
        "bed": _duty(bed) * profile.bed_rated_w,
        "hotend": _duty(hotend) * profile.hotend_rated_w,
        "base": profile.base_load_dc_w,
    }
    for name, rated_w in profile.fans.items():
        speed = _number(status.get(name), "speed")
        if speed is not None:
            components[f"fan:{name}"] = _duty(speed) * rated_w
    dc_w = sum(components.values())
    efficiency = profile.psu.efficiency(dc_w)
    components["external_ac"] = profile.external_ac_w
    return PowerEstimate(dc_w, dc_w / efficiency + profile.external_ac_w, efficiency, components)


def integrate_energy(
    samples: Iterable[tuple[datetime, dict[str, Any]]],
    profile: CalibrationProfile,
    max_gap_s: float = DEFAULT_MAX_GAP_S,
) -> EnergyResult:
    result = EnergyResult(
        0.0, 0.0, 0.0, 0, profile_name=profile.name, profile_version=profile.version
    )
    previous: tuple[datetime, PowerEstimate | None] | None = None
    for observed_at, status in sorted(samples, key=lambda item: item[0]):
        estimate = estimate_power(status, profile)
        if estimate is None:
            result.invalid_samples += 1
        if previous is not None:
            start, before = previous
            seconds = (observed_at - start).total_seconds()
            if seconds > 0:
                if before is None or estimate is None or seconds > max_gap_s:
                    result.uncovered_s += seconds
                else:
                    kwh = (before.wall_w + estimate.wall_w) / 2 * seconds / JOULES_PER_KWH
                    result.kwh += kwh
                    result.covered_s += seconds
                    result.intervals.append(EnergyInterval(start, observed_at, kwh))
        previous = (observed_at, estimate)
    return result
