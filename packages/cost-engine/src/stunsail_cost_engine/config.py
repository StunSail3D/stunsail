"""Load calibration profile and tariffs from YAML."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .profile import CalibrationProfile, PsuModel
from .tariff import Tariff


class EnergyConfigError(ValueError):
    pass


def load_energy_config(path: str | Path) -> tuple[CalibrationProfile, list[Tariff]]:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    try:
        p = raw["profile"]
        psu = p["psu"]
        profile = CalibrationProfile(
            version=int(p["version"]),
            name=str(p["name"]),
            bed_rated_w=float(p["bed_rated_w"]),
            hotend_rated_w=float(p["hotend_rated_w"]),
            base_load_dc_w=float(p.get("base_load_dc_w", 0.0)),
            psu=PsuModel(
                float(psu["rated_w"]),
                tuple((float(x), float(y)) for x, y in psu["efficiency_curve"]),
            ),
            fans={str(k): float(v) for k, v in (p.get("fans") or {}).items()},
            external_ac_w=float(p.get("external_ac_w", 0.0)),
            calibrated_against_meter=bool(p.get("calibrated_against_meter", False)),
        )
        tariffs = [
            Tariff(
                str(t["currency"]),
                Decimal(str(t["rate_per_kwh"])),
                _moment(t["effective_from"]),
                _moment(t["effective_to"]) if t.get("effective_to") else None,
            )
            for t in raw.get("tariffs") or []
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise EnergyConfigError(f"invalid energy configuration: {exc!r}") from exc
    if profile.psu.rated_w <= 0 or not profile.psu.curve:
        raise EnergyConfigError("psu requires a positive rated_w and an efficiency_curve")
    if any(not 0 < eff <= 1 for _, eff in profile.psu.curve):
        raise EnergyConfigError("psu efficiencies must be in (0, 1]")
    return profile, tariffs


def _moment(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        raise ValueError("tariff dates require a timezone offset")
    return moment
