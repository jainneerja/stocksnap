export interface Item {
  id: number;
  sku: string;
  name: string;
  description: string;
  category: string;
  tags: string;
  color: string;
  size: string;
  material: string;
  barcode: string | null;
  cost_cents: number;
  price_cents: number;
  quantity: number;
  low_stock_threshold: number;
  image_path: string | null;
  created_at: string;
  updated_at: string;
}

export type ItemInput = Partial<Omit<Item, "id" | "created_at" | "updated_at">> & { name: string };

export interface ScanResult {
  image_path: string;
  barcode: string | null;
  barcode_format: string | null;
  barcode_item: Item | null;
  matches: { item: Item; score: number }[];
}

export interface Draft {
  name: string;
  category: string;
  description: string;
  color: string;
  material: string;
  tags: string[];
}

export interface Sale {
  id: number;
  item_id: number;
  item_name: string;
  quantity: number;
  unit_price_cents: number;
  unit_cost_cents: number;
  note: string;
  sold_at: string;
}

export interface Expense {
  id: number;
  category: string;
  description: string;
  amount_cents: number;
  spent_on: string;
}

export interface Summary {
  start: string;
  end: string;
  sales_count: number;
  units_sold: number;
  revenue_cents: number;
  cogs_cents: number;
  gross_profit_cents: number;
  expenses_cents: number;
  net_profit_cents: number;
  stock_value_cents: number;
  expenses_by_category: Record<string, number>;
  top_items: { item_id: number; name: string; units: number; revenue_cents: number; profit_cents: number }[];
}

export interface Health {
  status: string;
  version: string;
  barcode: { available: boolean };
  vision: { available: boolean; model: string; detail: string };
  matcher: { available: boolean; model: string | null };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach StockSnap. Is the app running?");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const qs = (params: Record<string, string | boolean | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => req<Health>("/api/health"),

  items: (q = "", lowStock = false) =>
    req<Item[]>(`/api/items${qs({ q, low_stock: lowStock || undefined })}`),
  createItem: (data: ItemInput) => req<Item>("/api/items", json("POST", data)),
  updateItem: (id: number, data: Partial<ItemInput>) => req<Item>(`/api/items/${id}`, json("PATCH", data)),
  adjust: (id: number, delta: number) => req<Item>(`/api/items/${id}/adjust`, json("POST", { delta })),
  deleteItem: (id: number) => req<void>(`/api/items/${id}`, { method: "DELETE" }),

  scan: (file: Blob) => {
    const fd = new FormData();
    fd.append("file", file, "photo.jpg");
    return req<ScanResult>("/api/scan", { method: "POST", body: fd });
  },
  describe: (image_path: string) => req<Draft>("/api/describe", json("POST", { image_path })),

  sell: (item_id: number, quantity = 1, unit_price_cents?: number) =>
    req<Sale>("/api/sales", json("POST", { item_id, quantity, unit_price_cents })),
  sales: (start?: string, end?: string) => req<Sale[]>(`/api/sales${qs({ start, end })}`),
  voidSale: (id: number) => req<void>(`/api/sales/${id}`, { method: "DELETE" }),

  expenses: (start?: string, end?: string) => req<Expense[]>(`/api/expenses${qs({ start, end })}`),
  addExpense: (data: Omit<Expense, "id">) => req<Expense>("/api/expenses", json("POST", data)),
  deleteExpense: (id: number) => req<void>(`/api/expenses/${id}`, { method: "DELETE" }),

  summary: (start: string, end: string) => req<Summary>(`/api/reports/summary${qs({ start, end })}`),
  exportUrl: (kind: "sales" | "expenses" | "summary", start: string, end: string) =>
    `/api/reports/export.csv${qs({ kind, start, end })}`,
};

export const imageUrl = (p: string | null) => (p ? `/images/${p}` : "");
