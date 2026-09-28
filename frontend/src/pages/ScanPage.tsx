import { useState } from "react";
import { api, imageUrl, type Item, type ScanResult } from "../api";
import { emptyForm, ItemForm, type FormValues } from "../components/ItemForm";
import { PhotoButton } from "../components/PhotoButton";
import { money } from "../format";

type Stage =
  | { kind: "start" }
  | { kind: "scanning" }
  | { kind: "known"; scan: ScanResult; candidates: Item[] }
  | { kind: "new"; scan: ScanResult }
  | { kind: "saved"; item: Item };

export function ScanPage({ toast }: { toast: (msg: string) => void }) {
  const [stage, setStage] = useState<Stage>({ kind: "start" });
  const [form, setForm] = useState<FormValues>(emptyForm);
  const [aiBusy, setAiBusy] = useState(false);
  const [error, setError] = useState("");

  async function onPhoto(file: File) {
    setError("");
    setStage({ kind: "scanning" });
    try {
      const scan = await api.scan(file);
      const candidates = [
        ...(scan.barcode_item ? [scan.barcode_item] : []),
        ...scan.matches.map((m) => m.item).filter((i) => i.id !== scan.barcode_item?.id),
      ];
      if (candidates.length) setStage({ kind: "known", scan, candidates });
      else startNew(scan);
    } catch (e) {
      setError((e as Error).message);
      setStage({ kind: "start" });
    }
  }

  function startNew(scan: ScanResult) {
    setForm({ ...emptyForm, barcode: scan.barcode ?? "" });
    setStage({ kind: "new", scan });
    if (!scan.image_path) return; // manual entry, nothing for the AI to look at
    setAiBusy(true);
    api
      .describe(scan.image_path)
      .then((d) =>
        setForm((f) => ({
          ...f,
          name: d.name,
          category: d.category,
          description: d.description,
          color: d.color,
          material: d.material,
          tags: d.tags.join(", "),
        })),
      )
      .catch((e) => toast((e as Error).message))
      .finally(() => setAiBusy(false));
  }

  async function restock(item: Item, n: number) {
    const updated = await api.adjust(item.id, n);
    toast(`${updated.name}: now ${updated.quantity} in stock`);
    setStage({ kind: "start" });
  }

  return (
    <section>
      {stage.kind === "start" && (
        <div className="hero">
          <h1>Add stock</h1>
          <p className="muted">
            Snap a photo of an item. StockSnap reads any barcode, checks if you already have it,
            and drafts a listing with local AI — nothing leaves this computer.
          </p>
          <PhotoButton label="Take a photo" onPhoto={onPhoto} />
          <button className="link" onClick={() => startNew({ image_path: "", barcode: null, barcode_format: null, barcode_item: null, matches: [] })}>
            or add an item without a photo
          </button>
          {error && <p className="error">{error}</p>}
        </div>
      )}

      {stage.kind === "scanning" && (
        <div className="hero">
          <span className="spinner big" />
          <p>Looking at your photo…</p>
        </div>
      )}

      {stage.kind === "known" && (
        <div>
          <h2>Is it one of these?</h2>
          {stage.scan.barcode && (
            <p className="muted">
              Barcode {stage.scan.barcode} ({stage.scan.barcode_format})
            </p>
          )}
          <div className="cards">
            {stage.candidates.map((it) => (
              <div className="card" key={it.id}>
                {it.image_path && <img src={imageUrl(it.image_path)} alt="" />}
                <div className="card-body">
                  <strong>{it.name}</strong>
                  <span className="muted">
                    {it.sku} · {money(it.price_cents)} · {it.quantity} in stock
                  </span>
                  <div className="actions">
                    <button className="btn btn-primary" onClick={() => restock(it, 1)}>+1 stock</button>
                    <button className="btn btn-secondary" onClick={() => restock(it, 5)}>+5</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="actions">
            <button className="btn btn-secondary btn-big" onClick={() => startNew(stage.scan)}>
              No, it's a new item
            </button>
          </div>
        </div>
      )}

      {stage.kind === "new" && (
        <div>
          <h2>New item</h2>
          <ItemForm
            initial={form}
            imagePath={stage.scan.image_path || null}
            aiBusy={aiBusy}
            submitLabel="Save to inventory"
            onCancel={() => setStage({ kind: "start" })}
            onSubmit={async (data) => {
              const item = await api.createItem(data);
              setStage({ kind: "saved", item });
            }}
          />
        </div>
      )}

      {stage.kind === "saved" && (
        <div className="hero">
          <h2>Saved ✓</h2>
          <p>
            <strong>{stage.item.name}</strong> ({stage.item.sku}) — {stage.item.quantity} in stock at{" "}
            {money(stage.item.price_cents)}
          </p>
          <PhotoButton label="Scan the next item" onPhoto={onPhoto} />
        </div>
      )}
    </section>
  );
}
