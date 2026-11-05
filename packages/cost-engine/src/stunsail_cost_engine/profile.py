"""Per-printer calibration profile: everything the power estimator assumes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PsuModel:
    """Piecewise-linear PSU efficiency curve as (load fraction of rated output, efficiency)."""

    rated_w: float
    curve: tuple[tuple[float, float], ...]

    def efficiency(self, dc_load_w: float) -> float:
        fraction = max(dc_load_w, 0.0) / self.rated_w
        points = sorted(self.curve)
        if fraction <= points[0][0]:
            return points[0][1]
        for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
            if fraction <= x1:
                return y0 + (y1 - y0) * (fraction - x0) / (x1 - x0)
        return points[-1][1]


@dataclass(frozen=True)
class CalibrationProfile:
    """Topology: heaters, fans and base load are DC loads behind the PSU; external_ac_w is not.

    `fans` maps a Moonraker status object name to its rated watts at full speed. Fan power is
    modelled as linear in speed. Bump `version` whenever any assumption changes so stored
    job results stay reproducible.
    """

    version: int
    name: str
    bed_rated_w: float
    hotend_rated_w: float
    base_load_dc_w: float
    psu: PsuModel
    fans: dict[str, float] = field(default_factory=dict)
    external_ac_w: float = 0.0
    bed_object: str = "heater_bed"
    hotend_object: str = "extruder"
    calibrated_against_meter: bool = False

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> CalibrationProfile:
        psu = data["psu"]
        return cls(
            **{**data, "psu": PsuModel(float(psu["rated_w"]), tuple(map(tuple, psu["curve"])))}
        )
