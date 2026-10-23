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
  brand: string;
  attributes: string;
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
  brand: string;
  price_cents: number | null;
  tags: string[];
  mode?: DescribeMode; // how this draft was made
  seconds?: number;
}

export type DescribeMode = "instant" | "fast" | "full";

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

export type SortKey = "newest" | "oldest" | "name" | "price_high" | "price_low" | "stock_low" | "stock_high";
export type StockState = "all" | "in" | "low" | "out";

export interface ItemFilters {
  q?: string;
  category?: string;
  material?: string;
  brand?: string;
  batch_id?: number;
  stock?: StockState;
  sort?: SortKey;
}

export interface Facet {
  name: string;
  items: number;
  units: number;
}

export interface Facets {
  total_items: number;
  total_units: number;
  stock_value_cents: number;
  categories: Facet[];
  materials: Facet[];
  brands: Facet[];
  batches: { id: number; label: string; items: number }[];
  stock: { in: number; low: number; out: number };
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

const qs = (params: Record<string, string | number | boolean | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => req<Health>("/api/health"),

  items: (f: ItemFilters | string = {}) => {
    const p = typeof f === "string" ? { q: f } : f;
    return req<Item[]>(`/api/items${qs({ ...p, batch_id: p.batch_id ? String(p.batch_id) : undefined })}`);
  },
  facets: () => req<Facets>("/api/items/facets"),
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
  describe: (image_path: string, tag_image_path?: string, hint?: string) =>
    req<Draft>("/api/describe", json("POST", { image_path, tag_image_path, hint: hint ?? "" })),

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
  categories: string[];
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
  brand: string;
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
  Pick<Group, "name" | "description" | "category" | "tags" | "color" | "size" | "material" | "brand" | "cost_cents" | "price_cents" | "count_override" | "include">
> & { add_to_existing?: boolean };

export interface StockRow {
  item_id: number;
  sku: string;
  name: string;
  size: string;
  category: string;
  image_path: string | null;
  opening: number;
  added: number;
  sold: number;
  adjusted: number;
  closing: number;
  unit_cost_cents: number;
  closing_value_cents: number;
}

export interface CategoryStock {
  category: string;
  items: number;
  opening: number;
  added: number;
  sold: number;
  adjusted: number;
  closing: number;
  closing_value_cents: number;
}

export interface StockMonth {
  month: string;
  rows: StockRow[];
  by_category: CategoryStock[];
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
  // Clear the AI's names/descriptions and run again, telling it what the items are.
  redescribe: (id: number, note: string) =>
    req<Batch>(`/api/batches/${id}/describe`, json("POST", { redo: true, note })),
  updateGroup: (id: number, groupId: number, data: GroupUpdate) =>
    req<Batch>(`/api/batches/${id}/groups/${groupId}`, json("PATCH", data)),
  bulkEdit: (id: number, data: { price_cents?: number; cost_cents?: number; category?: string }) =>
    req<Batch>(`/api/batches/${id}/bulk-edit`, json("POST", data)),
  save: (id: number) => req<Item[]>(`/api/batches/${id}/save`, { method: "POST" }),
  discard: (id: number) => req<void>(`/api/batches/${id}`, { method: "DELETE" }),
};

export const stockMonth = (month: string, category = "") =>
  req<StockMonth>(`/api/reports/stock${qs({ month, category })}`);
export const barcodeUrl = (itemId: number) => `/api/items/${itemId}/barcode.svg`;

// ------------------------------------------------------------------ shops

export type ShopKind = "clothing" | "jewellery" | "soap" | "candle" | "other";

export interface Shop {
  slug: string;
  name: string;
  kind: ShopKind;
  sku_prefix: string;
  low_stock_default: number;
  ai_context: string;
  describe_mode: DescribeMode;
  name_template: string;
  desc_template: string;
  has_logo: boolean;
  created_at: string;
}

export interface ShopInput {
  name: string;
  kind: ShopKind;
  sku_prefix: string;
  low_stock_default: number;
  ai_context: string;
  describe_mode: DescribeMode;
  name_template: string;
  desc_template: string;
}

export const shops = {
  list: () => req<{ shops: Shop[]; current: string | null; kinds: ShopKind[] }>("/api/shops"),
  create: (data: ShopInput) => req<Shop>("/api/shops", json("POST", data)),
  update: (slug: string, data: Partial<ShopInput>) => req<Shop>(`/api/shops/${slug}`, json("PATCH", data)),
  select: (slug: string) => req<Shop>(`/api/shops/${slug}/select`, { method: "POST" }),
  previewDescription: (data: { kind: string; name: string; name_template: string; desc_template: string }) =>
    req<{ name: string; description: string; default_name_template: string; default_desc_template: string }>(
      "/api/shops/preview-description",
      json("POST", data),
    ),
  suggestPrefix: (name: string) => req<{ sku_prefix: string }>(`/api/shops/suggest-prefix${qs({ name })}`),
  uploadLogo: (slug: string, file: Blob) => {
    const fd = new FormData();
    fd.append("file", file, "logo.png");
    return req<Shop>(`/api/shops/${slug}/logo`, { method: "POST", body: fd });
  },
  removeLogo: (slug: string) => req<Shop>(`/api/shops/${slug}/logo`, { method: "DELETE" }),
};

export const logoUrl = (shop: Shop, version = 0) => (shop.has_logo ? `/api/shops/${shop.slug}/logo?v=${version}` : "");

export const KIND_LABELS: Record<ShopKind, { label: string; hint: string }> = {
  clothing: { label: "Clothing", hint: "Tees, hoodies, dresses, kids" },
  jewellery: { label: "Jewellery", hint: "Earrings, rings, necklaces" },
  soap: { label: "Soaps & bath", hint: "Bars, bath bombs, butters" },
  candle: { label: "Candles", hint: "Jars, tins, wax melts" },
  other: { label: "Something else", hint: "Anything else you sell" },
};

// ------------------------------------------------------------- image lab

export interface LabOutput {
  file: string;
  look: string;
  label: string;
  seconds: number;
  note: string;
  kb: number;
}

export interface LabJob {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  message: string;
  created: number;
  outputs: LabOutput[];
  notes: string[];
  total_s: number;
  cutout_s?: number;
  options: { looks: string[]; scene: string; title: string };
}

export interface LabStatus {
  cutout: { engine: string; model: string; quality: string; hint?: string };
  generator: { available: boolean; model: string; device?: string; loaded?: boolean; detail: string };
  looks: Record<string, string>;
  scenes: string[];
}

export const lab = {
  status: () => req<LabStatus>("/api/lab/status"),
  jobs: () => req<LabJob[]>("/api/lab/jobs"),
  job: (id: string) => req<LabJob>(`/api/lab/jobs/${id}`),
  create: (file: Blob, opts: { looks: string[]; scene: string; custom_prompt: string; ai_count: number; title: string; bullets: string; scene_ids?: string[] }) => {
    const fd = new FormData();
    fd.append("scene_ids", (opts.scene_ids ?? []).join(","));
    fd.append("file", file, "photo.jpg");
    fd.append("looks", opts.looks.join(","));
    fd.append("scene", opts.scene);
    fd.append("custom_prompt", opts.custom_prompt);
    fd.append("ai_count", String(opts.ai_count));
    fd.append("title", opts.title);
    fd.append("bullets", opts.bullets);
    return req<LabJob>("/api/lab/jobs", { method: "POST", body: fd });
  },
  remove: (id: string) => req<void>(`/api/lab/jobs/${id}`, { method: "DELETE" }),
  fileUrl: (id: string, name: string) => `/api/lab/files/${id}/${name}`,
  zipUrl: (id: string, prefix: string) => `/api/lab/jobs/${id}/zip${qs({ prefix })}`,
};

// ---------------------------------------------------------------- scenes

export interface Stroke {
  points: [number, number][]; // fractions of the scene
  r: number; // brush radius, fraction of the scene width
}

export interface Scene {
  id: string;
  name: string;
  width: number;
  height: number;
  created: number;
  cx: number;
  top: number;
  bottom: number;
  rx: number;
  tilt: number;
  top_box: [number, number, number, number] | null;
  keep: Stroke[];
  remove: Stroke[];
  keep_outlines: [number, number][][]; // exact outlines (polygons), fractions of the scene
  remove_outlines: [number, number][][];
  shading: number;
  shadow: number;
  scale: number;
  empty_base?: boolean; // base photo without an old product: nothing is removed
}

export type SceneUpdate = Partial<Omit<Scene, "id" | "width" | "height" | "created" | "top_box">> & {
  top_box?: [number, number, number, number] | [];
};

export const scenes = {
  list: () => req<Scene[]>("/api/scenes"),
  create: (file: Blob, name: string) => {
    const fd = new FormData();
    fd.append("file", file, "scene.jpg");
    fd.append("name", name);
    return req<Scene>("/api/scenes", { method: "POST", body: fd });
  },
  update: (id: string, data: SceneUpdate) => req<Scene>(`/api/scenes/${id}`, json("PUT", data)),
  /** Local AI finds the product, its top part, the face and what to keep, and sets the scene up. */
  auto: (id: string, data: { product: string; keep: string; top_piece: boolean }) =>
    req<{ scene: Scene; notes: string[]; seconds: number; found: Record<string, number> }>(
      `/api/scenes/${id}/auto`,
      json("POST", data),
    ),
  remove: (id: string) => req<void>(`/api/scenes/${id}`, { method: "DELETE" }),
  fileUrl: (id: string, name: "scene.jpg" | "layers.jpg" | "thumb.jpg", v = 0) => `/api/scenes/${id}/files/${name}?v=${v}`,
  /** Render a product photo (or a saved item) into the scene; returns an object URL. */
  tryOn: async (id: string, src: { file?: Blob; itemId?: number }) => {
    const fd = new FormData();
    if (src.file) fd.append("file", src.file, "product.jpg");
    if (src.itemId != null) fd.append("item_id", String(src.itemId));
    const r = await fetch(`/api/scenes/${id}/try`, { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "Couldn't make the preview");
    return URL.createObjectURL(await r.blob());
  },
};

export interface ListingOutput {
  item_id: number;
  sku: string;
  file: string;
  label: string;
}

export interface ListingJob {
  id: string;
  status: "queued" | "running" | "done";
  done: number;
  total: number;
  outputs: ListingOutput[];
  notes: string[];
  total_s: number;
}

export const listing = {
  create: (items: { item_id: number; scene_ids: string[] }[], white: boolean) =>
    req<ListingJob>("/api/listing-photos", json("POST", { items, white })),
  get: (id: string) => req<ListingJob>(`/api/listing-photos/${id}`),
  fileUrl: (id: string, name: string) => `/api/listing-photos/${id}/files/${name}`,
  zipUrl: (id: string) => `/api/listing-photos/${id}/zip`,
};

// ---- product catalogue (a folder of photos -> PDF)
export interface CatalogueItem {
  id: number;
  file: string;
  photo: string;
  name: string;
  description: string;
  price: string;
  code: string;
  include: boolean;
  status: "queued" | "ready" | "failed";
  size?: string;
  design?: string;
  colour?: string;
}

export interface Catalogue {
  id: string;
  created: number;
  title: string;
  subtitle: string;
  columns: 2 | 3;
  layout: "grid" | "designs";
  product: string;
  hint: string;
  status: "running" | "done";
  done: number;
  total: number;
  notes: string[];
  mode: string;
  items: CatalogueItem[];
}

export interface CatalogueSummary {
  id: string;
  title: string;
  created: number;
  total: number;
  status: string;
  cover: string | null;
}

export interface FolderResult {
  shop: string;
  owner: string;
  catalogues: { id: string; title: string; photos: number; designs: number; saved: string[]; notes: string[] }[];
}

export type CatalogueEdit = Partial<Pick<Catalogue, "title" | "subtitle" | "columns" | "layout" | "product">> & {
  items?: (Partial<Pick<CatalogueItem, "name" | "description" | "price" | "code" | "include" | "colour">> & { id: number })[];
};

export const catalogues = {
  list: () => req<CatalogueSummary[]>("/api/catalogues"),
  create: (files: File[], opts: { title: string; hint: string; clean_background: boolean; describe: boolean }) => {
    const fd = new FormData();
    for (const f of files) {
      fd.append("files", f, f.name);
      // where the photo sits in the picked folder: "Size 7/Design 2/Red.jpg"
      fd.append("paths", (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    }
    fd.append("title", opts.title);
    fd.append("hint", opts.hint);
    fd.append("clean_background", String(opts.clean_background));
    fd.append("describe", String(opts.describe));
    return req<Catalogue>("/api/catalogues", { method: "POST", body: fd });
  },
  get: (id: string) => req<Catalogue>(`/api/catalogues/${id}`),
  update: (id: string, data: CatalogueEdit) => req<Catalogue>(`/api/catalogues/${id}`, json("PUT", data)),
  remove: (id: string) => req<void>(`/api/catalogues/${id}`, { method: "DELETE" }),
  photoUrl: (id: string, photo: string) => `/api/catalogues/${id}/photos/${photo}`,
  pdfUrl: (id: string, prices = true) => `/api/catalogues/${id}/pdf${prices ? "" : "?prices=false"}`,
  /** Read a shop folder on this computer; one catalogue (with and without prices) per product folder. */
  fromFolder: (path: string) =>
    req<FolderResult>("/api/catalogues/from-folder", json("POST", { path, save_to_folder: true })),
};
