import { useState } from "react";
import { api, imageUrl, type Item, type ScanResult } from "../api";
import { emptyForm, formFromItem, ItemForm, type FormValues } from "../components/ItemForm";
import { PhotoButton } from "../components/PhotoButton";
import { money, toDollars } from "../format";
import { useShop } from "../shop";

/** `base` is set when adding a new size of a product you already stock. */
type Stage =
  | { kind: "start" }
  | { kind: "scanning" }
  | { kind: "known"; scan: ScanResult; candidates: Item[] }
  | { kind: "tag"; scan: ScanResult; base?: Item; busy?: boolean }
  | { kind: "new"; scan: ScanResult; base?: Item; tagPath?: string }
  | { kind: "saved"; item: Item };

const NO_PHOTO: ScanResult = { image_path: "", barcode: null, barcode_format: null, barcode_item: null, matches: [] };

export function ScanPage({ toast }: { toast: (msg: string) => void }) {
  const { shop } = useShop();
  const [stage, setStage] = useState<Stage>({ kind: "start" });
  const [form, setForm] = useState<FormValues>(emptyForm);
  const [aiBusy, setAiBusy] = useState(false);
  // The seller's own words for what the item is. Kept between items: people
  // usually add several of the same kind in a row.
  const [hint, setHint] = useState("");
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
      else setStage({ kind: "tag", scan });
    } catch (e) {
      setError((e as Error).message);
      setStage({ kind: "start" });
    }
  }

  async function onTagPhoto(scan: ScanResult, base: Item | undefined, file: File) {
    setStage({ kind: "tag", scan, base, busy: true });
    try {
      const { image_path } = await api.savePhoto(file);
      openForm(scan, base, image_path);
    } catch (e) {
      toast((e as Error).message);
      setStage({ kind: "tag", scan, base });
    }
  }

  function openForm(scan: ScanResult, base?: Item, tagPath?: string) {
    // New size of an existing product: copy its details, leave size (and stock) blank.
    const start = base
      ? { ...formFromItem(base), size: "", sku: "", barcode: scan.barcode ?? "", quantity: "1" }
      : { ...emptyForm, barcode: scan.barcode ?? "" };
    setForm(start);
    setStage({ kind: "new", scan, base, tagPath });
    if (!scan.image_path) return; // manual entry, nothing for the AI to look at
    runAi(scan, base, tagPath, hint);
  }

  function runAi(scan: ScanResult, base: Item | undefined, tagPath: string | undefined, note: string) {
    setAiBusy(true);
    api
      .describe(scan.image_path, tagPath, note.trim())
      .then((d) =>
        setForm((f) => {
          const price = d.price_cents ? toDollars(d.price_cents) : "";
          if (base) {
            // Keep the product's details; only take what the tag tells us.
            return { ...f, size: d.size || f.size, price: price || f.price };
          }
          return {
            ...f,
            name: d.name,
            category: d.category,
            description: d.description,
            color: d.color,
            material: d.material,
            brand: d.brand ?? "",
            size: d.size,
            price,
            tags: d.tags.join(", "),
          };
        }),
      )
      .catch((e) => toast((e as Error).message))
      .finally(() => setAiBusy(false));
  }

  async function restock(item: Item, n: number) {
    const updated = await api.adjust(item.id, n);
    toast(`${updated.name}${updated.size ? ` (${updated.size})` : ""}: now ${updated.quantity} in stock`);
    setStage({ kind: "start" });
  }

  return (
    <section>
      {stage.kind === "start" && (
        <div className="hero">
          <h1>Add stock to {shop.name}</h1>
          <p className="muted">
            Snap a photo of an item. StockSnap reads any barcode, checks if you already have it, and drafts a
            listing with local AI. Nothing leaves this computer.
          </p>
          <label className="hint-field">
            What is it? <span className="muted small">(optional, tells the AI)</span>
            <input value={hint} onChange={(e) => setHint(e.target.value)} maxLength={300}
              placeholder="e.g. embroidered outfit for a small statue" />
          </label>
          <PhotoButton label="Take a photo" onPhoto={onPhoto} />
          <button className="link" onClick={() => openForm(NO_PHOTO)}>
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
                  <strong>
                    {it.name}
                    {it.size && <span className="size-chip">{it.size}</span>}
                  </strong>
                  <span className="muted">
                    {it.sku} · {money(it.price_cents)} · {it.quantity} in stock
                  </span>
                  <div className="actions">
                    <button className="btn btn-primary" onClick={() => restock(it, 1)}>+1 stock</button>
                    <button className="btn btn-secondary" onClick={() => restock(it, 5)}>+5</button>
                    <button className="btn btn-secondary" onClick={() => setStage({ kind: "tag", scan: stage.scan, base: it })}>
                      Different size
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="actions">
            <button className="btn btn-secondary btn-big" onClick={() => setStage({ kind: "tag", scan: stage.scan })}>
              No, it's a new item
            </button>
          </div>
        </div>
      )}

      {stage.kind === "tag" && (
        <div className="hero">
          <div className="thumbs">
            {stage.scan.image_path && <img src={imageUrl(stage.scan.image_path)} alt="" />}
            <div className="tag-ph" aria-hidden>
              <TagIcon />
            </div>
          </div>
          <h2>Is there a size or price tag?</h2>
          <p className="muted">
            {stage.base
              ? `Adding a new size of ${stage.base.name}. Snap the size label and the AI will read it.`
              : "Snap a close-up of the label or hang tag and the AI will read the size and price for you."}
          </p>
          {stage.busy ? (
            <span className="spinner big" />
          ) : (
            <>
              <PhotoButton label="Photo of the tag" onPhoto={(f) => onTagPhoto(stage.scan, stage.base, f)} />
              <button className="btn btn-secondary" onClick={() => openForm(stage.scan, stage.base)}>
                No tag, skip
              </button>
            </>
          )}
        </div>
      )}

      {stage.kind === "new" && (
        <div>
          <h2>{stage.base ? `New size of ${stage.base.name}` : "New item"}</h2>
          {stage.scan.image_path && !stage.base && (
            <form
              className="ai-redo"
              onSubmit={(e) => {
                e.preventDefault();
                runAi(stage.scan, stage.base, stage.tagPath, hint);
              }}
            >
              <input value={hint} onChange={(e) => setHint(e.target.value)} maxLength={300}
                aria-label="Tell the AI what this is" placeholder="AI got it wrong? Tell it what this is" />
              <button className="btn btn-secondary" disabled={aiBusy || !hint.trim()}>Ask AI again</button>
            </form>
          )}
          <ItemForm
            initial={form}
            imagePath={stage.scan.image_path || null}
            tagImagePath={stage.tagPath}
            aiBusy={aiBusy}
            submitLabel="Save to inventory"
            onCancel={() => setStage({ kind: "start" })}
            onAddStock={(it) => restock(it, 1)}
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
            <strong>{stage.item.name}</strong>
            {stage.item.size && ` · size ${stage.item.size}`} ({stage.item.sku}): {stage.item.quantity} in stock at{" "}
            {money(stage.item.price_cents)}
          </p>
          <PhotoButton label="Scan the next item" onPhoto={onPhoto} />
        </div>
      )}
    </section>
  );
}

function TagIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <circle cx="8" cy="8" r="1.6" />
    </svg>
  );
}
