"""Effective-dated tariffs and cost calculation that splits intervals across boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .energy import EnergyInterval


@dataclass(frozen=True)
class Tariff:
    currency: str
    rate_per_kwh: Decimal
    effective_from: datetime
    effective_to: datetime | None = None


@dataclass(frozen=True)
class CostLine:
    tariff: Tariff
    kwh: float
    cost: Decimal


@dataclass
class CostResult:
    currency: str | None
    total: Decimal
    lines: list[CostLine] = field(default_factory=list)
    uncosted_kwh: float = 0.0


def calculate_cost(intervals: Iterable[EnergyInterval], tariffs: list[Tariff]) -> CostResult:
    """Price each interval by the tariff(s) in force, splitting proportionally by time.

    Energy with no applicable tariff is reported as `uncosted_kwh`, never silently priced.
    """
    currencies = {tariff.currency for tariff in tariffs}
    if len(currencies) > 1:
        raise ValueError("tariffs mix currencies")
    kwh_by_tariff = dict.fromkeys(range(len(tariffs)), 0.0)
    uncosted = 0.0
    for interval in intervals:
        duration = (interval.end - interval.start).total_seconds()
        if duration <= 0:
            continue
        covered = 0.0
        for index, tariff in enumerate(tariffs):
            start = max(interval.start, tariff.effective_from)
            end = min(interval.end, tariff.effective_to or interval.end)
            overlap = (end - start).total_seconds()
            if overlap > 0:
                kwh_by_tariff[index] += interval.kwh * overlap / duration
                covered += overlap
        uncosted += interval.kwh * max(duration - covered, 0.0) / duration
    lines = [
        CostLine(tariff, kwh_by_tariff[i], tariff.rate_per_kwh * Decimal(repr(kwh_by_tariff[i])))
        for i, tariff in enumerate(tariffs)
        if kwh_by_tariff[i] > 0
    ]
    return CostResult(
        next(iter(currencies), None),
        sum((line.cost for line in lines), Decimal(0)),
        lines,
        uncosted,
    )
