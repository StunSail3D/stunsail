import { currencySymbol } from "./currency";

export function pricedValue(
  amount: string,
  currency: string | null | undefined,
): string {
  const symbol = currencySymbol(currency);
  return symbol ? `${symbol} ${amount}` : amount;
}

export function money(
  amount: string | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount == null) return "—";
  const value = Number(amount).toFixed(2);
  if (!currency) return value;
  return pricedValue(value, currency);
}

export const kwh = (value: string | null | undefined): string =>
  value == null ? "—" : `${Number(value).toFixed(4)} kWh`;

export const grams = (value: string | null | undefined): string =>
  value == null ? "—" : `${Number(value).toFixed(1)} g`;

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

export const dateTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleString() : "—";

export function coverage(covered: number, uncovered: number): number {
  const total = covered + uncovered;
  return total > 0 ? covered / total : 0;
}

export const basisLabel = (basis: string): string =>
  basis === "estimated"
    ? "Estimated (not meter-calibrated)"
    : "Meter-calibrated";

export const MATERIAL_DENSITY: Record<string, string> = {
  PLA: "1.24",
  PETG: "1.27",
  ABS: "1.04",
  ASA: "1.07",
  TPU: "1.21",
  Nylon: "1.14",
};
