import { describe, expect, it } from "vitest";
import catalog from "./filament-database.json";
import { coloursFor, freeMaterials, materials, reelImage } from "./filaments";

describe("filament catalogue", () => {
  it("uses the workbook materials and availability rather than a generic colour list", () => {
    expect(new Set(materials.map((entry) => entry.name)).size).toBe(
      materials.length,
    );
    expect(materials.every((entry) => !entry.name.includes(" / "))).toBe(true);
    for (const name of [
      "PLA",
      "PLA Silk",
      "PLA Dual-Colour",
      "PLA Tri-Colour",
      "PLA Rainbow",
      "PLA Galaxy",
      "PLA Sparkle",
      "PETG",
      "ABS",
    ])
      expect(freeMaterials.has(name)).toBe(true);
    for (const name of [
      "PLA+ (Tough PLA)",
      "PLA-CF (Carbon Fibre)",
      "PLA Magnetic",
      "PLA Iron-Fill",
      "PLA Glow-in-the-Dark",
      "PLA Marble",
      "PLA Stone",
      "PLA Wood-Fill",
      "PLA Metal-Fill",
      "PLA Conductive",
    ])
      expect(freeMaterials.has(name)).toBe(false);
    expect(coloursFor("PLA").some((entry) => entry.colour === "White")).toBe(
      true,
    );
    expect(coloursFor("ABS").some((entry) => entry.colour === "White")).toBe(
      true,
    );
    expect(coloursFor("PLA")).toEqual(
      catalog.availability.filter((entry) => entry.material === "PLA"),
    );
    expect(coloursFor("ABS")).toEqual(
      catalog.availability.filter((entry) => entry.material === "ABS"),
    );
    for (const material of materials) {
      expect(coloursFor(material.name)).toEqual(
        catalog.availability.filter(
          (entry) => entry.material === material.sourceName,
        ),
      );
    }
    expect(coloursFor("Silk PLA")).toEqual(coloursFor("PLA Silk"));
    expect(
      materials.find((entry) => entry.name === "PLA Silk")?.properties,
    ).toEqual(
      catalog.materials.find((entry) => entry.name === "Silk PLA")?.properties,
    );
  });
  it("maps every workbook colour to a local spool image", () => {
    for (const colour of catalog.colours)
      expect(reelImage(colour.name)).toBeTruthy();
    expect(reelImage("unknown colour")).toBeNull();
  });
});
