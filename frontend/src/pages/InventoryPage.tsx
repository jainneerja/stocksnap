import { useCallback, useEffect, useState } from "react";
import { api, imageUrl, type Facets, type Item, type SortKey, type StockState } from "../api";
import { CategoryChips } from "../components/CategoryChips";
import { formFromItem, ItemForm } from "../components/ItemForm";
import { money } from "../format";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "Newest first" },
  { key: "oldest", label: "Oldest first" },
  { key: "name", label: "Name A–Z" },
  { key: "price_high", label: "Price: high to low" },
  { key: "price_low", label: "Price: low to high" },
  { key: "stock_low", label: "Stock: lowest first" },
  { key: "stock_high", label: "Stock: highest first" },
];

interface View {
  q: string;
  category: string;
  stock: StockState;
  sort: SortKey;
  batch: number | "";
  layout: "grid" | "list";
}

const DEFAULT_VIEW: View = { q: "", category: "", stock: "all", sort: "newest", batch: "", layout: "grid" };

// Remember filters between visits (per browser). Storage can be unavailable, so never rely on it.
function loadView(): View {
  try {
    const saved = JSON.parse(localStorage.getItem("stocksnap.inventoryView") || "{}");
    return { ...DEFAULT_VIEW, ...saved, q: "" };
  } catch {
    return DEFAULT_VIEW;
  }
}

export function InventoryPage({ toast }: { toast: (msg: string) => void }) {
  const [view, setView] = useState<View>(loadView);
  const [items, setItems] = useState<Item[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [editing, setEditing] = useState<Item | null>(null);
  const [loading, setLoading] = useState(true);

  const set = (patch: Partial<View>) => setView((v) => ({ ...v, ...patch }));

  useEffect(() => {
    try {
      const { q: _q, ...rest } = view;
      void _q;
      localStorage.setItem("stocksnap.inventoryView", JSON.stringify(rest));
    } catch {
      /* private mode etc. */
    }
  }, [view]);

  const load = useCallback(async () => {
    const [its, f] = await Promise.all([
      api.items({
        q: view.q,
        category: view.category,
        stock: view.stock,
        sort: view.sort,
        batch_id: view.batch || undefined,
      }),
      api.facets(),
    ]);
    setItems(its);
    setFacets(f);
    setLoading(false);
  }, [view.q, view.category, view.stock, view.sort, view.batch]);

  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => toast(e.message)), 150);
    return () => clearTimeout(t);
  }, [load, toast]);

  async function adjust(it: Item, delta: number) {
    const u = await api.adjust(it.id, delta);
    setItems((all) => all.map((x) => (x.id === u.id ? u : x)));
  }

  async function remove(it: Item) {
    if (!window.confirm(`Delete ${it.name}?`)) return;
    try {
      await api.deleteItem(it.id);
      setEditing(null);
      toast("Deleted");
      load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  if (editing)
    return (
      <section>
        <button className="link" onClick={() => setEditing(null)}>← Inventory</button>
        <h2>Edit {editing.name}</h2>
        <ItemForm
          initial={formFromItem(editing)}
          imagePath={editing.image_path}
          editingId={editing.id}
          categories={facets?.categories.map((c) => c.name)}
          submitLabel="Save changes"
          onCancel={() => setEditing(null)}
          onSubmit={async (data) => {
            await api.updateItem(editing.id, data);
            toast("Saved");
            setEditing(null);
            load();
          }}
        />
        <button className="link danger" onClick={() => remove(editing)}>Delete this item</button>
      </section>
    );

  const filtered = view.q || view.category || view.stock !== "all" || view.batch !== "";
  const units = items.reduce((s, i) => s + Math.max(i.quantity, 0), 0);
  const value = items.reduce((s, i) => s + Math.max(i.quantity, 0) * i.cost_cents, 0);

  return (
    <section>
      <div className="page-head">
        <h1>Inventory</h1>
        {facets && (
          <span className="muted">
            {facets.total_items} items · {facets.total_units} units · {money(facets.stock_value_cents)} at cost
          </span>
        )}
      </div>

      <input
        className="search"
        type="search"
        value={view.q}
        onChange={(e) => set({ q: e.target.value })}
        placeholder="Search name, SKU, tag, metal or barcode"
      />

      {facets && (
        <CategoryChips
          facets={facets.categories}
          total={facets.total_items}
          value={view.category}
          onChange={(category) => set({ category })}
        />
      )}

      <div className="filter-bar">
        <select aria-label="Stock" value={view.stock} onChange={(e) => set({ stock: e.target.value as StockState })}>
          <option value="all">All stock</option>
          <option value="in">In stock{facets ? ` (${facets.stock.in})` : ""}</option>
          <option value="low">Running low{facets ? ` (${facets.stock.low})` : ""}</option>
          <option value="out">Sold out{facets ? ` (${facets.stock.out})` : ""}</option>
        </select>
        {facets && facets.batches.length > 0 && (
          <select
            aria-label="Batch"
            value={view.batch}
            onChange={(e) => set({ batch: e.target.value ? Number(e.target.value) : "" })}
          >
            <option value="">All batches</option>
            {facets.batches.map((b) => (
              <option key={b.id} value={b.id}>
                Batch {b.label} ({b.items})
              </option>
            ))}
          </select>
        )}
        <select aria-label="Sort" value={view.sort} onChange={(e) => set({ sort: e.target.value as SortKey })}>
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        <div className="seg" role="group" aria-label="Layout">
          <button className={view.layout === "grid" ? "on" : ""} onClick={() => set({ layout: "grid" })} aria-label="Grid view" title="Grid">
            <GridIcon />
          </button>
          <button className={view.layout === "list" ? "on" : ""} onClick={() => set({ layout: "list" })} aria-label="List view" title="List">
            <ListIcon />
          </button>
        </div>
      </div>

      <p className="muted small result-line">
        {filtered ? (
          <>
            Showing {items.length} of {facets?.total_items ?? items.length} · {units} units · {money(value)} at cost ·{" "}
            <button className="link" onClick={() => setView({ ...DEFAULT_VIEW, layout: view.layout, sort: view.sort })}>
              Clear filters
            </button>
          </>
        ) : (
          <>
            {items.length} {items.length === 1 ? "item" : "items"} · {SORTS.find((s) => s.key === view.sort)?.label.toLowerCase()}
          </>
        )}
        <a className="link export" href="/api/items/export.csv">Export CSV</a>
      </p>

      {!loading && items.length === 0 && (
        <div className="empty">
          {filtered ? "Nothing matches these filters." : "No items yet. Add some with Add or Bulk."}
        </div>
      )}

      {view.layout === "grid" ? (
        <div className="inv-grid">
          {items.map((it) => (
            <button key={it.id} className="inv-card" onClick={() => setEditing(it)}>
              <div className="inv-photo">
                {it.image_path ? <img src={imageUrl(it.image_path)} alt="" loading="lazy" /> : <span className="inv-ph">{it.name[0]}</span>}
                <QtyBadge item={it} />
              </div>
              <span className="inv-name">
                {it.name}
                {it.size && <span className="size-chip">{it.size}</span>}
              </span>
              <span className="inv-meta">
                {money(it.price_cents)}
                <span className="muted"> · {it.sku}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <ul className="inv">
          {items.map((it) => (
            <li key={it.id} className={it.quantity <= 0 ? "out" : it.quantity <= it.low_stock_threshold ? "low" : ""}>
              {it.image_path ? <img src={imageUrl(it.image_path)} alt="" loading="lazy" /> : <div className="thumb-ph">{it.name[0]}</div>}
              <button className="inv-main" onClick={() => setEditing(it)}>
                <strong>{it.name}</strong>
                <span className="muted">
                  {it.size && <span className="size-chip">{it.size}</span>}
                  {it.category && `${it.category} · `}
                  {it.sku} · {money(it.price_cents)}
                </span>
              </button>
              <div className="stepper">
                <button onClick={() => adjust(it, -1)} aria-label="one less">−</button>
                <span>{it.quantity}</span>
                <button onClick={() => adjust(it, 1)} aria-label="one more">+</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function QtyBadge({ item }: { item: Item }) {
  const state = item.quantity <= 0 ? "out" : item.quantity <= item.low_stock_threshold ? "low" : "ok";
  return (
    <span className={`qty ${state}`} title={state === "out" ? "Sold out" : state === "low" ? "Running low" : "In stock"}>
      {state === "out" ? "Sold out" : item.quantity}
    </span>
  );
}

function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="8" rx="2" />
      <rect x="3" y="13" width="8" height="8" rx="2" /><rect x="13" y="13" width="8" height="8" rx="2" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="3" y="4" width="18" height="4" rx="1.5" /><rect x="3" y="10" width="18" height="4" rx="1.5" />
      <rect x="3" y="16" width="18" height="4" rx="1.5" />
    </svg>
  );
}
