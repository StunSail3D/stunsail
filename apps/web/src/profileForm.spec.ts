import { describe, expect, it } from "vitest";
import {
  FormError,
  parseCurve,
  parseFans,
  profilePayload,
  type ProfileForm,
} from "./profileForm";

const form: ProfileForm = {
  name: "ender",
  version: 2,
  bedW: 220,
  hotendW: 60,
  baseLoadW: 19.32,
  externalAcW: 0,
  psuRatedW: 350,
  curve: "1.0:0.89, 0.05:0.72",
  fans: "fan: 2.88, heater_fan hotend_Fan: 2.4",
  calibrated: false,
};

describe("profile form", () => {
  it("parses and sorts the efficiency curve", () => {
    expect(parseCurve("1.0:0.89, 0.05:0.72")).toEqual([
      [0.05, 0.72],
      [1, 0.89],
    ]);
  });

  it.each(["0.5:0.9", "a:b, 0.5:0.9", "0.5:1.4, 1:0.9", "0:0.5, 1:0.9"])(
    "rejects a bad curve %s",
    (text) => {
      expect(() => parseCurve(text)).toThrow(FormError);
    },
  );

  it("parses fans whose names contain spaces", () => {
    expect(parseFans("fan: 2.88, heater_fan hotend_Fan: 2.4")).toEqual({
      fan: 2.88,
      "heater_fan hotend_Fan": 2.4,
    });
    expect(parseFans("")).toEqual({});
    expect(() => parseFans("fan")).toThrow(FormError);
    expect(() => parseFans("fan: -1")).toThrow(FormError);
  });

  it("builds the API payload", () => {
    const payload = profilePayload(form);
    expect(payload.data.psu).toEqual({
      rated_w: 350,
      curve: [
        [0.05, 0.72],
        [1, 0.89],
      ],
    });
    expect(payload.data.fans["heater_fan hotend_Fan"]).toBe(2.4);
    expect(payload.calibrated_against_meter).toBe(false);
  });

  it("validates required numbers", () => {
    expect(() => profilePayload({ ...form, name: " " })).toThrow(FormError);
    expect(() => profilePayload({ ...form, bedW: -1 })).toThrow(FormError);
    expect(() => profilePayload({ ...form, psuRatedW: 0 })).toThrow(FormError);
  });
});
