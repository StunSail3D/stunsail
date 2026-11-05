# Phase 2 — Power and energy engine

Status: **Implemented; meter calibration pending**

## Implemented

- [x] Configurable estimator: heater duty × rated watts, linear fan loads, DC base
  load, PSU efficiency curve applied once to DC load, external AC added after.
- [x] Trapezoidal integration to kWh. Intervals longer than 5 s or touching an
  invalid sample are **not integrated or interpolated**; they are reported as
  uncovered time and lower the coverage figure.
- [x] Per-printer calibration profile with a version and a
  `calibrated_against_meter` flag. Results carry `basis="estimated"`.
- [x] Effective-dated tariffs; intervals spanning a tariff boundary are split by
  time; energy with no tariff is reported as uncosted, never silently priced.
- [x] Reproducible report: `uv run stunsail-agent energy-report --config agent.yaml
  --energy energy.yaml` (template: `deployment/installer/configs/energy.example.yaml`).

## First real result (5 Nov 2026, `Cube_PETG_7m44s.gcode`, profile v1)

0.0172 kWh, 122 W average, R0.08, 82% coverage (115 s uncovered from two Agent
restarts). Estimated, uncalibrated.

## Not yet met

- [ ] Comparison against plug-meter data (no meter yet). Until then every figure is
  an estimate and the profile values below are assumptions.
- [ ] Confirm the hotend heater wattage (TZ-E3 V3 cartridge label), whether the
  Orange Pi 3 LTS is powered from the printer PSU or its own adapter
  (`external_ac_w`), the fan wattages, and the PSU efficiency curve.
- [ ] Per-job results are computed on demand; persisting them with the profile
  version belongs to Core (Phase 3).

## Calibration procedure (when a meter is available)

Record wall energy over: idle with heaters off (fixes `base_load_dc_w` plus host),
bed heat-up, hotend heat-up, and a full print. Adjust the profile, bump `version`,
and set `calibrated_against_meter: true`. Keep the meter identity and conditions
with the new profile.
