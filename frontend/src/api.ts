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
  size: string;
  price_cents: number | null;
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
  savePhoto: (file: Blob) => {
    const fd = new FormData();
    fd.append("file", file, "tag.jpg");
    return req<{ image_path: string }>("/api/photos", { method: "POST", body: fd });
  },
  describe: (image_path: string, tag_image_path?: string) =>
    req<Draft>("/api/describe", json("POST", { image_path, tag_image_path })),

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

// ------------------------------------------------------------ bulk intake

export interface Question {
  key: string;
  label: string;
  kind: "select" | "text" | "money";
  options: string[];
  field: string | null;
  help: string;
}

export interface Preset {
  key: string;
  label: string;
  mode: "unique" | "identical";
  background: string;
  tips: string[];
  questions: Question[];
  ai_hint: string;
  per_photo: string;
}

export interface Detection {
  id: number;
  number: number;
  bbox: [number, number, number, number];
  include: boolean;
  group_id: number;
}

export interface BatchPhoto {
  id: number;
  image_path: string;
  width: number;
  height: number;
  detections: Detection[];
}

export interface ItemRef {
  id: number;
  sku: string;
  name: string;
  size: string;
  quantity: number;
  price_cents: number;
}

export interface Group {
  id: number;
  status: "pending" | "done" | "failed";
  name: string;
  description: string;
  category: string;
  tags: string;
  color: string;
  size: string;
  material: string;
  cost_cents: number;
  price_cents: number;
  include: boolean;
  count: number;
  count_override: number | null;
  numbers: number[];
  crops: string[];
  existing_item: ItemRef | null;
  item: ItemRef | null;
}

export interface Batch {
  id: number;
  preset: string;
  preset_label: string;
  mode: "unique" | "identical";
  answers: Record<string, string>;
  status: "capturing" | "describing" | "review" | "saved";
  describing: boolean;
  created_at: string;
  photos: BatchPhoto[];
  groups: Group[];
  progress: { pieces: number; groups: number; done: number; failed: number; units: number };
  warning: string;
}

export type GroupUpdate = Partial<
  Pick<Group, "name" | "description" | "category" | "tags" | "color" | "size" | "material" | "cost_cents" | "price_cents" | "count_override" | "include">
> & { add_to_existing?: boolean };

export interface StockRow {
  item_id: number;
  sku: string;
  name: string;
  size: string;
  opening: number;
  added: number;
  sold: number;
  adjusted: number;
  closing: number;
  unit_cost_cents: number;
  closing_value_cents: number;
}

export interface StockMonth {
  month: string;
  rows: StockRow[];
  totals: Record<string, number>;
}

export const bulk = {
  presets: () => req<Preset[]>("/api/presets"),
  open: () => req<Batch[]>("/api/batches"),
  create: (preset: string, answers: Record<string, string>) =>
    req<Batch>("/api/batches", json("POST", { preset, answers })),
  get: (id: number) => req<Batch>(`/api/batches/${id}`),
  addPhoto: (id: number, file: Blob) => {
    const fd = new FormData();
    fd.append("file", file, "tray.jpg");
    return req<Batch>(`/api/batches/${id}/photos`, { method: "POST", body: fd });
  },
  toggle: (id: number, detId: number, include: boolean) =>
    req<Batch>(`/api/batches/${id}/detections/${detId}`, json("PATCH", { include })),
  describe: (id: number) => req<Batch>(`/api/batches/${id}/describe`, { method: "POST" }),
  updateGroup: (id: number, groupId: number, data: GroupUpdate) =>
    req<Batch>(`/api/batches/${id}/groups/${groupId}`, json("PATCH", data)),
  bulkEdit: (id: number, data: { price_cents?: number; cost_cents?: number; category?: string }) =>
    req<Batch>(`/api/batches/${id}/bulk-edit`, json("POST", data)),
  save: (id: number) => req<Item[]>(`/api/batches/${id}/save`, { method: "POST" }),
  discard: (id: number) => req<void>(`/api/batches/${id}`, { method: "DELETE" }),
};

export const stockMonth = (month: string) => req<StockMonth>(`/api/reports/stock?month=${month}`);
export const barcodeUrl = (itemId: number) => `/api/items/${itemId}/barcode.svg`;
