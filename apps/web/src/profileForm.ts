export interface ProfileForm {
  name: string;
  version: number;
  bedW: number;
  hotendW: number;
  baseLoadW: number;
  externalAcW: number;
  psuRatedW: number;
  curve: string;
  fans: string;
  calibrated: boolean;
}

export class FormError extends Error {}

// "0.05:0.72, 0.5:0.89" -> [[0.05, 0.72], [0.5, 0.89]]
export function parseCurve(text: string): [number, number][] {
  const points = text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [load, efficiency] = part.split(":").map((v) => Number(v));
      if (!Number.isFinite(load) || !Number.isFinite(efficiency)) {
        throw new FormError(
          `Bad efficiency point "${part}" (use load:efficiency)`,
        );
      }
      if (load <= 0 || load > 1 || efficiency <= 0 || efficiency > 1) {
        throw new FormError(
          `Efficiency point "${part}" must be between 0 and 1`,
        );
      }
      return [load, efficiency] as [number, number];
    });
  if (points.length < 2)
    throw new FormError("Enter at least two efficiency points");
  return points.sort((a, b) => a[0] - b[0]);
}

// "fan: 2.88, heater_fan hotend_Fan: 2.4" -> { fan: 2.88, "heater_fan hotend_Fan": 2.4 }
export function parseFans(text: string): Record<string, number> {
  const fans: Record<string, number> = {};
  for (const part of text
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)) {
    const index = part.lastIndexOf(":");
    const name = part.slice(0, index).trim();
    const watts = Number(part.slice(index + 1));
    if (index < 1 || !name || !Number.isFinite(watts) || watts < 0) {
      throw new FormError(`Bad fan entry "${part}" (use name: watts)`);
    }
    fans[name] = watts;
  }
  return fans;
}

export function profilePayload(form: ProfileForm) {
  if (!form.name.trim()) throw new FormError("Name is required");
  for (const [label, value] of [
    ["Bed watts", form.bedW],
    ["Hotend watts", form.hotendW],
    ["Base load", form.baseLoadW],
    ["External AC", form.externalAcW],
  ] as const) {
    if (!Number.isFinite(value) || value < 0)
      throw new FormError(`${label} must be 0 or more`);
  }
  if (!(form.psuRatedW > 0)) throw new FormError("PSU rating must be positive");
  return {
    name: form.name.trim(),
    version: form.version,
    calibrated_against_meter: form.calibrated,
    data: {
      bed_rated_w: form.bedW,
      hotend_rated_w: form.hotendW,
      base_load_dc_w: form.baseLoadW,
      external_ac_w: form.externalAcW,
      psu: { rated_w: form.psuRatedW, curve: parseCurve(form.curve) },
      fans: parseFans(form.fans),
    },
  };
}
