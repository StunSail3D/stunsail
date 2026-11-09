import { ref } from "vue";
import { request } from "./api";
import catalog from "./currency-catalog.json";

export interface CurrencySettings {
  currency: string;
  symbol: string;
}

const preferredCurrencies = [
  { code: "ZAR", flag: "🇿🇦", name: "South Africa", symbol: "R" },
  { code: "USD", flag: "🇺🇸", name: "United States", symbol: "$" },
  { code: "EUR", flag: "🇪🇺", name: "Euro area", symbol: "€" },
  { code: "GBP", flag: "🇬🇧", name: "United Kingdom", symbol: "£" },
  { code: "AUD", flag: "🇦🇺", name: "Australia", symbol: "A$" },
  { code: "CAD", flag: "🇨🇦", name: "Canada", symbol: "C$" },
  { code: "NZD", flag: "🇳🇿", name: "New Zealand", symbol: "NZ$" },
  { code: "CHF", flag: "🇨🇭", name: "Switzerland", symbol: "CHF" },
  { code: "JPY", flag: "🇯🇵", name: "Japan", symbol: "¥" },
  { code: "CNY", flag: "🇨🇳", name: "China", symbol: "¥" },
  { code: "INR", flag: "🇮🇳", name: "India", symbol: "₹" },
  { code: "BRL", flag: "🇧🇷", name: "Brazil", symbol: "R$" },
  { code: "SEK", flag: "🇸🇪", name: "Sweden", symbol: "kr" },
  { code: "NOK", flag: "🇳🇴", name: "Norway", symbol: "kr" },
  { code: "DKK", flag: "🇩🇰", name: "Denmark", symbol: "kr" },
];
export const currencies = [
  ...preferredCurrencies,
  ...catalog.filter(
    (entry) => !preferredCurrencies.some((item) => item.code === entry.code),
  ),
];

export const currencySettings = ref<CurrencySettings | null>(null);
export const currencyError = ref("");

export function currencySymbol(code: string | null | undefined): string {
  if (!code) return "";
  if (currencySettings.value?.currency === code)
    return currencySettings.value.symbol;
  const entry = currencies.find((item) => item.code === code);
  if (!entry || entry.symbol === code) return code;
  const ambiguous =
    currencies.some(
      (item) => item.code !== code && item.symbol === entry.symbol,
    ) ||
    (currencySettings.value?.currency !== code &&
      currencySettings.value?.symbol === entry.symbol);
  return ambiguous ? `${entry.symbol} (${code})` : entry.symbol;
}

export async function loadCurrency(): Promise<void> {
  try {
    currencySettings.value =
      await request<CurrencySettings>("/settings/currency");
    currencyError.value = "";
  } catch (error) {
    currencyError.value =
      error instanceof Error ? error.message : String(error);
    throw error;
  }
}

export async function saveCurrency(settings: CurrencySettings): Promise<void> {
  currencySettings.value = await request<CurrencySettings>(
    "/settings/currency",
    "PUT",
    settings,
  );
  currencyError.value = "";
}
