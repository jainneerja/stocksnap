import { useCallback, useEffect, useState } from "react";
import { api, imageUrl, type Item } from "../api";
import { formFromItem, ItemForm } from "../components/ItemForm";
import { money } from "../format";

export function InventoryPage({ toast }: { toast: (msg: string) => void }) {
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [editing, setEditing] = useState<Item | null>(null);

  const load = useCallback(() => api.items(q, lowOnly).then(setItems), [q, lowOnly]);

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
        <h2>Edit {editing.name}</h2>
        <ItemForm
          initial={formFromItem(editing)}
          imagePath={editing.image_path}
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

  const units = items.reduce((s, i) => s + Math.max(i.quantity, 0), 0);
  const value = items.reduce((s, i) => s + Math.max(i.quantity, 0) * i.cost_cents, 0);

  return (
    <section>
      <div className="toolbar">
        <input className="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search inventory" />
        <label className="check">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> Low stock
        </label>
        <a className="btn btn-secondary" href="/api/items/export.csv">Export CSV</a>
      </div>
      <p className="muted">
        {items.length} {items.length === 1 ? "item" : "items"} · {units} units · {money(value)} at cost
      </p>
      <ul className="inv">
        {items.map((it) => (
          <li key={it.id} className={it.quantity <= it.low_stock_threshold ? "low" : ""}>
            {it.image_path ? <img src={imageUrl(it.image_path)} alt="" /> : <div className="thumb-ph">{it.name[0]}</div>}
            <button className="inv-main" onClick={() => setEditing(it)}>
              <strong>{it.name}</strong>
              <span className="muted">
                {it.sku}
                {it.size && ` · ${it.size}`} · {money(it.price_cents)}
              </span>
            </button>
            <div className="stepper">
              <button onClick={() => adjust(it, -1)} aria-label="one less">−</button>
              <span>{it.quantity}</span>
              <button onClick={() => adjust(it, 1)} aria-label="one more">+</button>
            </div>
          </li>
        ))}
        {!items.length && <li className="muted">Nothing here yet.</li>}
      </ul>
    </section>
  );
}
