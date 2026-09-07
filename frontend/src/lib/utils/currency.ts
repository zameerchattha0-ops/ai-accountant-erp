export function formatCurrency(
  amount: number,
  currency: string = "PKR",
  options?: Intl.NumberFormatOptions
): string {
  if (!Number.isFinite(amount)) return "Rs. 0.00";

  const symbols: Record<string, string> = {
    PKR: "Rs.",
    USD: "$",
    EUR: "€",
    GBP: "£",
    AED: "د.إ",
    SAR: "﷼",
    INR: "₹",
  };

  const symbol = symbols[currency] || currency;

  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...options,
  }).format(Math.abs(amount));

  const prefix = amount < 0 ? "-" : "";
  return `${prefix}${symbol} ${formatted}`;
}

export function formatCompact(amount: number, currency: string = "PKR"): string {
  if (!Number.isFinite(amount)) return formatCurrency(0, currency);
  if (Math.abs(amount) >= 1_000_000) {
    return formatCurrency(amount / 1_000_000, currency, { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + "M";
  }
  if (Math.abs(amount) >= 100_000) {
    return formatCurrency(amount / 1_000, currency, { maximumFractionDigits: 0, minimumFractionDigits: 0 }) + "K";
  }
  return formatCurrency(amount, currency);
}
