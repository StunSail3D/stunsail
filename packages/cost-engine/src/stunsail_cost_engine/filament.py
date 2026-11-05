"""Filament length/mass/cost conversions."""

from __future__ import annotations

import math
from decimal import Decimal

GRAM_PLACES = Decimal("0.001")
MONEY_PLACES = Decimal("0.0001")


def filament_mass_g(length_mm: float, diameter_mm: Decimal, density_g_cm3: Decimal) -> Decimal:
    """Mass of a filament length: cylinder volume (mm^3 -> cm^3) times density."""
    if length_mm < 0:
        raise ValueError("length must not be negative")
    volume_cm3 = math.pi * (float(diameter_mm) / 2) ** 2 * length_mm / 1000.0
    return (Decimal(repr(volume_cm3)) * density_g_cm3).quantize(GRAM_PLACES)


def filament_cost(mass_g: Decimal, purchase_cost: Decimal, opening_weight_g: Decimal) -> Decimal:
    """Cost of a mass at the spool's purchase price per gram."""
    if opening_weight_g <= 0:
        raise ValueError("opening weight must be positive")
    return (mass_g * purchase_cost / opening_weight_g).quantize(MONEY_PLACES)
