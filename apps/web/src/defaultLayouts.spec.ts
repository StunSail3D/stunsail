import { describe, expect, it } from "vitest";
import { defaultLayout } from "./defaultLayouts";

describe("default layouts", () => {
  it("uses the saved desktop layout with any printer identity", () => {
    expect(
      defaultLayout("dashboard", 3, [
        { id: "printer-another" },
        { id: "month" },
        { id: "recent" },
        { id: "printer-second" },
      ]),
    ).toEqual([
      { i: "printer-another", x: 0, y: 0, w: 2, h: 7 },
      { i: "month", x: 2, y: 0, w: 1, h: 7 },
      { i: "recent", x: 0, y: 7, w: 3, h: 4 },
      { i: "printer-second", x: 0, y: 11, w: 1, h: 8 },
    ]);
  });
  it("uses captured layouts for settings, spools and reports", () => {
    expect(
      defaultLayout("settings", 3, [{ id: "profiles" }, { id: "agents" }]),
    ).toEqual([
      { i: "profiles", x: 0, y: 6, w: 2, h: 11 },
      { i: "agents", x: 0, y: 17, w: 1, h: 9 },
    ]);
    expect(defaultLayout("spools", 3, [{ id: "add" }])[0]).toMatchObject({
      w: 3,
      h: 7,
    });
    expect(defaultLayout("reports", 3, [{ id: "summary" }])[0]).toMatchObject({
      w: 3,
      h: 5,
    });
  });
  it("keeps the existing responsive defaults on other sizes", () => {
    expect(
      defaultLayout("spools", 1, [{ id: "add", height: 18 }])[0],
    ).toMatchObject({ w: 1, h: 18 });
  });
});
