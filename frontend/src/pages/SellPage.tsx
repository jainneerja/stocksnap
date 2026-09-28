import { useCallback, useEffect, useState } from "react";
import { api, imageUrl, type Item, type Sale } from "../api";
import { PhotoButton } from "../components/PhotoButton";
import { isoDate, money } from "../format";

export function SellPage({ toast }: { toast: (msg: string) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [today, setToday] = useState<Sale[]>([]);
  const [found, setFound] = useState<Item[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const d = isoDate();
    const [its, sales] = await Promise.all([api.items(q), api.sales(d, d)]);
    setItems(its);
    setToday(sales);
  }, [q]);

  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => toast(e.message)), 150);
    return () => clearTimeout(t);
  }, [load, toast]);

  async function sell(item: Item) {
    try {
      await api.sell(item.id, 1);
      toast(`Sold 1 × ${item.name} for ${money(item.price_cents)}`);
      setFound(null);
      await load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function undo(s: Sale) {
    await api.voidSale(s.id);
    toast(`Undid sale of ${s.item_name}`);
    await load();
  }

  async function findByPhoto(file: File) {
    setBusy(true);
    try {
      const r = await api.scan(file);
      const list = [
        ...(r.barcode_item ? [r.barcode_item] : []),
        ...r.matches.map((m) => m.item).filter((i) => i.id !== r.barcode_item?.id),
      ];
      if (!list.length) toast("No match found — search by name instead.");
      setFound(list);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const total = today.reduce((s, x) => s + x.quantity * x.unit_price_cents, 0);
  const shown = found ?? items;

  return (
    <section>
      <div className="sell-top">
        <input
          className="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setFound(null);
          }}
          placeholder="Search name, SKU, tag or barcode"
        />
        <PhotoButton label={busy ? "Finding…" : "Find by photo"} onPhoto={findByPhoto} disabled={busy} variant="secondary" />
      </div>
      {found && (
        <p className="muted">
          Photo matches · <button className="link" onClick={() => setFound(null)}>show all</button>
        </p>
      )}

      <div className="grid">
        {shown.map((it) => (
          <button key={it.id} className="tile" disabled={it.quantity <= 0} onClick={() => sell(it)}>
            {it.image_path ? <img src={imageUrl(it.image_path)} alt="" /> : <div className="tile-ph">{it.name[0]}</div>}
            <span className="tile-name">{it.name}</span>
            <span className="tile-meta">
              {money(it.price_cents)} · {it.quantity > 0 ? `${it.quantity} left` : "sold out"}
            </span>
          </button>
        ))}
        {!shown.length && <p className="muted">No items yet — add some on the Add stock tab.</p>}
      </div>

      <h2>
        Today <span className="muted">· {money(total)}</span>
      </h2>
      <ul className="list">
        {today.map((s) => (
          <li key={s.id}>
            <span>
              {s.quantity} × {s.item_name}
            </span>
            <span>{money(s.quantity * s.unit_price_cents)}</span>
            <button className="link" onClick={() => undo(s)}>undo</button>
          </li>
        ))}
        {!today.length && <li className="muted">No sales yet today.</li>}
      </ul>
    </section>
  );
}
