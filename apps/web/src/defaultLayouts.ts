export interface DefaultPosition {
  x: number;
  y: number;
  w: number;
  h: number;
}

const layouts: Record<string, Record<string, DefaultPosition>> = {
  dashboard: {
    printer: { x: 0, y: 0, w: 2, h: 7 },
    month: { x: 2, y: 0, w: 1, h: 7 },
    recent: { x: 0, y: 7, w: 3, h: 4 },
  },
  spools: { add: { x: 0, y: 0, w: 3, h: 7 } },
  reports: { summary: { x: 0, y: 0, w: 3, h: 5 } },
  settings: {
    admin: { x: 0, y: 0, w: 1, h: 6 },
    currency: { x: 1, y: 0, w: 2, h: 6 },
    profiles: { x: 0, y: 6, w: 2, h: 11 },
    tariffs: { x: 2, y: 6, w: 1, h: 11 },
    agents: { x: 0, y: 17, w: 1, h: 9 },
    printers: { x: 1, y: 17, w: 2, h: 9 },
  },
};

export function defaultLayout(
  page: string,
  columns: number,
  cards: { id: string; height?: number }[],
): (DefaultPosition & { i: string })[] {
  const preset = columns === 3 ? layouts[page] : undefined;
  if (!preset)
    return cards.map((card, index) => ({
      i: card.id,
      x: index % columns,
      y: Math.floor(index / columns) * 24,
      w: 1,
      h: card.height ?? 8,
    }));

  let firstPrinter = true;
  let bottom = Math.max(0, ...Object.values(preset).map((p) => p.y + p.h));
  return cards.map((card) => {
    let position = preset[card.id];
    if (
      page === "dashboard" &&
      card.id.startsWith("printer-") &&
      firstPrinter
    ) {
      position = preset.printer;
      firstPrinter = false;
    }
    if (position) return { i: card.id, ...position };
    const item = { i: card.id, x: 0, y: bottom, w: 1, h: card.height ?? 8 };
    bottom += item.h;
    return item;
  });
}
