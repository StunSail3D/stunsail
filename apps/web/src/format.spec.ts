import { describe, expect, it } from "vitest";
import { basisLabel, coverage, duration, grams, kwh, money } from "./format";

describe("format", () => {
  it("formats money from decimal strings without floats leaking", () => {
    expect(money("4.5", "ZAR")).toBe("ZAR 4.50");
    expect(money(null, "ZAR")).toBe("—");
    expect(money("0.0775", null)).toBe("0.08");
  });

  it("formats energy and weight", () => {
    expect(kwh("0.01723")).toBe("0.0172 kWh");
    expect(grams("12.345")).toBe("12.3 g");
    expect(grams(null)).toBe("—");
  });

  it("formats durations", () => {
    expect(duration(null)).toBe("—");
    expect(duration(45)).toBe("45s");
    expect(duration(464)).toBe("7m 44s");
    expect(duration(3720)).toBe("1h 02m");
  });

  it("computes coverage and never divides by zero", () => {
    expect(coverage(82, 18)).toBeCloseTo(0.82);
    expect(coverage(0, 0)).toBe(0);
  });

  it("labels estimated energy honestly", () => {
    expect(basisLabel("estimated")).toContain("not meter-calibrated");
  });
});
