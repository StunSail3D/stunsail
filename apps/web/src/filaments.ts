import catalog from "./filament-database.json";

const materialNames: Record<string, string[]> = {
  "PLA+ (Tough PLA)": ["PLA+ (Tough PLA)"],
  "High-Speed PLA": ["PLA High-Speed"],
  "Matte PLA": ["PLA Matte"],
  "Silk PLA": ["PLA Silk"],
  "Dual / Tri-Colour & Rainbow PLA": [
    "PLA Dual-Colour",
    "PLA Tri-Colour",
    "PLA Rainbow",
  ],
  "Marble / Stone PLA": ["PLA Marble", "PLA Stone"],
  "Wood-Fill PLA": ["PLA Wood-Fill"],
  "Glow-in-the-Dark PLA": ["PLA Glow-in-the-Dark"],
  "Galaxy / Sparkle PLA": ["PLA Galaxy", "PLA Sparkle"],
  "Colour-Change PLA": ["PLA Colour-Change"],
  "Metal-Fill PLA": ["PLA Metal-Fill"],
  "Magnetic / Iron-Fill PLA": ["PLA Magnetic", "PLA Iron-Fill"],
  "Conductive PLA": ["PLA Conductive"],
  "PLA-CF (Carbon Fibre)": ["PLA-CF (Carbon Fibre)"],
  "ABS-CF / ABS-GF": ["ABS-CF", "ABS-GF"],
  "TPE / TPU 85A (Soft)": ["TPE 85A (Soft)", "TPU 85A (Soft)"],
  "Nylon (PA6 / PA12)": ["Nylon (PA6)", "Nylon (PA12)"],
  "PEI (ULTEM 1010 / 9085)": ["PEI (ULTEM 1010)", "PEI (ULTEM 9085)"],
};

export const materials = catalog.materials.flatMap((source) =>
  (materialNames[source.name] ?? [source.name]).map((name) => ({
    ...source,
    name,
    sourceName: source.name,
  })),
);
export const freeMaterials = new Set([
  "PLA",
  "PLA High-Speed",
  "PLA Matte",
  "PLA Silk",
  "PLA Dual-Colour",
  "PLA Tri-Colour",
  "PLA Rainbow",
  "PLA Galaxy",
  "PLA Sparkle",
  "PLA Colour-Change",
  "PETG",
  "ABS",
]);
export const coloursFor = (material: string) => {
  const source =
    materials.find((entry) => entry.name === material)?.sourceName ?? material;
  return catalog.availability.filter((entry) => entry.material === source);
};

const reelFiles: Record<string, string> = {
  White: "white",
  Black: "black",
  Grey: "gray",
  "Light Grey": "light_gray",
  "Dark Grey": "dark_gray",
  "Natural / Unpigmented": "trans_nat",
  "Transparent / Clear": "trans_nat",
  Red: "red",
  "Dark Red / Burgundy": "burgundy",
  Pink: "pink",
  "Hot Pink / Magenta": "hot_pink",
  Orange: "orange",
  Yellow: "yellow",
  "Beige / Tan": "beige",
  "Skin / Flesh": "skin",
  "Light Green / Lime": "lime",
  Green: "green",
  "Dark Green": "miltary_green",
  Mint: "mint",
  Teal: "teal",
  Cyan: "cyan",
  "Sky Blue": "sky_blue",
  Blue: "blue",
  Navy: "navy",
  Purple: "purple",
  Lavender: "lavender",
  Brown: "brown",
  Gold: "silk_gold",
  Silver: "silver",
  Bronze: "bronze",
  Copper: "copper",
  "Rose Gold": "rose_gold",
  "Fluorescent Yellow": "fluoro_yellow",
  "Fluorescent Orange": "fluoro_orange",
  "Fluorescent Green": "fluoro_green",
  "Fluorescent Pink": "fluoro_pink",
  "Glow Green (Glow-in-the-dark)": "glow-in-dark",
  "Glow Blue (Glow-in-the-dark)": "glow-dark-blue",
  "Rainbow / Multicolour": "rainbow",
  "Gradient / Dual-tone": "gradient",
  "Marble Effect": "marble",
  "Granite / Stone Effect": "granite",
  "Wood Tone - Light": "wood_light",
  "Wood Tone - Dark": "wood_dark",
  "Colour-Change (Temperature)": "color_change_temp",
  "Colour-Change (UV / Sunlight)": "color_change_uv",
  "Galaxy / Sparkle Effect": "galaxy",
};

export function reelImage(colour: string | null): string | null {
  if (!colour) return null;
  const file = reelFiles[colour];
  return file ? `/spools/reel_${file}.png` : null;
}
