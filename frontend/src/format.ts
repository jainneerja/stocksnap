const fmt = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });

export const money = (cents: number) => fmt.format(cents / 100);

/** "12.5" / "$12.50" -> 1250. Returns null when not a valid amount. */
export function toCents(text: string): number | null {
  const clean = text.replace(/[^0-9.]/g, "");
  if (!clean) return 0;
  const n = Number(clean);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

export const toDollars = (cents: number) => (cents ? (cents / 100).toFixed(2) : "");

/** Local calendar date as YYYY-MM-DD. */
export function isoDate(d = new Date()): string {
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

export function monthRange(year: number, month: number): [string, string] {
  const start = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);
  const today = new Date();
  return [isoDate(start), isoDate(last > today ? today : last)];
}
