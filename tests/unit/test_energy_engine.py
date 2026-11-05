from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stunsail_cost_engine import (
    CalibrationProfile,
    PsuModel,
    Tariff,
    calculate_cost,
    estimate_power,
    integrate_energy,
)

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
FLAT_PSU = PsuModel(rated_w=100, curve=((0.0, 0.8), (1.0, 0.8)))


def profile(**overrides):
    values = dict(
        version=1,
        name="test",
        bed_rated_w=200.0,
        hotend_rated_w=50.0,
        base_load_dc_w=10.0,
        psu=FLAT_PSU,
        fans={"fan": 4.0},
    )
    values.update(overrides)
    return CalibrationProfile(**values)


def status(bed=0.0, hotend=0.0, fan=0.0):
    return {
        "heater_bed": {"power": bed},
        "extruder": {"power": hotend},
        "fan": {"speed": fan},
    }


def test_estimate_applies_psu_efficiency_once_and_adds_ac_after():
    estimate = estimate_power(status(bed=0.5, hotend=1.0, fan=0.5), profile(external_ac_w=5.0))
    # DC: 100 bed + 50 hotend + 10 base + 2 fan = 162 W; wall = 162 / 0.8 + 5
    assert estimate.dc_w == pytest.approx(162.0)
    assert estimate.wall_w == pytest.approx(162.0 / 0.8 + 5.0)
    assert estimate.components_w["bed"] == pytest.approx(100.0)


def test_duty_is_clamped_and_missing_heater_is_invalid():
    assert estimate_power(status(bed=3.0), profile()).components_w["bed"] == 200.0
    assert estimate_power({"extruder": {"power": 0.1}}, profile()) is None
    assert (
        estimate_power({"heater_bed": {"power": "x"}, "extruder": {"power": 0}}, profile()) is None
    )


def test_psu_curve_interpolates_and_clamps():
    psu = PsuModel(100, ((0.1, 0.6), (0.5, 0.9)))
    assert psu.efficiency(0) == 0.6
    assert psu.efficiency(30) == pytest.approx(0.75)
    assert psu.efficiency(500) == 0.9


def test_integrates_constant_load():
    # 10 W DC base / 0.8 = 12.5 W for 3600 s = 0.0125 kWh
    samples = [(T0 + timedelta(seconds=i), status()) for i in range(0, 3601)]
    result = integrate_energy(samples, profile())
    assert result.kwh == pytest.approx(0.0125)
    assert result.coverage == 1.0 and result.average_w == pytest.approx(12.5)
    assert result.basis == "estimated" and result.profile_version == 1


def test_trapezoid_between_changing_samples():
    samples = [(T0, status(bed=0.0)), (T0 + timedelta(seconds=2), status(bed=1.0))]
    # wall 12.5 W then 262.5 W, mean 137.5 W over 2 s
    assert integrate_energy(samples, profile()).kwh == pytest.approx(137.5 * 2 / 3_600_000)


def test_gaps_are_not_integrated():
    samples = [
        (T0, status()),
        (T0 + timedelta(seconds=1), status()),
        (T0 + timedelta(seconds=301), status()),
        (T0 + timedelta(seconds=302), status()),
    ]
    result = integrate_energy(samples, profile())
    assert result.uncovered_s == 300 and result.covered_s == 2
    assert result.kwh == pytest.approx(12.5 * 2 / 3_600_000)
    assert result.coverage == pytest.approx(2 / 302)


def test_invalid_sample_breaks_both_adjacent_intervals():
    samples = [
        (T0, status()),
        (T0 + timedelta(seconds=1), {"fan": {"speed": 0}}),
        (T0 + timedelta(seconds=2), status()),
        (T0 + timedelta(seconds=3), status()),
    ]
    result = integrate_energy(samples, profile())
    assert result.invalid_samples == 1
    assert result.covered_s == 1 and result.uncovered_s == 2


def test_cost_splits_interval_across_tariff_boundary():
    boundary = T0 + timedelta(seconds=30)
    tariffs = [
        Tariff("ZAR", Decimal("4.00"), T0 - timedelta(days=1), boundary),
        Tariff("ZAR", Decimal("6.00"), boundary),
    ]
    samples = [(T0, status()), (T0 + timedelta(seconds=60), status())]
    result = integrate_energy(samples, profile(), max_gap_s=120)
    cost = calculate_cost(result.intervals, tariffs)
    half = result.kwh / 2
    assert [line.kwh for line in cost.lines] == [pytest.approx(half)] * 2
    assert float(cost.total) == pytest.approx(half * 4 + half * 6)
    assert cost.uncosted_kwh == 0 and cost.currency == "ZAR"


def test_energy_without_tariff_is_reported_uncosted():
    samples = [(T0, status()), (T0 + timedelta(seconds=10), status())]
    result = integrate_energy(samples, profile())
    tariffs = [Tariff("ZAR", Decimal("4.5"), T0 + timedelta(seconds=5))]
    cost = calculate_cost(result.intervals, tariffs)
    assert cost.uncosted_kwh == pytest.approx(result.kwh / 2)


def test_tariff_boundary_respects_timezone_offsets():
    plus2 = timezone(timedelta(hours=2))
    tariff = Tariff("ZAR", Decimal("4.5"), datetime(2026, 11, 5, 12, 0, tzinfo=plus2))
    samples = [(T0, status()), (T0 + timedelta(seconds=10), status())]
    cost = calculate_cost(integrate_energy(samples, profile()).intervals, [tariff])
    assert cost.uncosted_kwh == 0


def test_mixed_currencies_rejected():
    with pytest.raises(ValueError):
        calculate_cost([], [Tariff("ZAR", Decimal(1), T0), Tariff("USD", Decimal(1), T0)])
