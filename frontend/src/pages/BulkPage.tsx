import { useCallback, useEffect, useRef, useState } from "react";
import { barcodeUrl, bulk, imageUrl, type Batch, type BatchPhoto, type Group, type Item, type Preset } from "../api";
import { PhotoButton } from "../components/PhotoButton";
import { money, toCents, toDollars } from "../format";
import { useShop } from "../shop";

type View =
  | { kind: "home" }
  | { kind: "setup"; preset: Preset }
  | { kind: "batch"; id: number }
  | { kind: "labels"; batch: Batch; items: Item[] };

export function BulkPage({ toast, aiReady }: { toast: (m: string) => void; aiReady: boolean }) {
  const [view, setView] = useState<View>({ kind: "home" });
  const [presets, setPresets] = useState<Preset[]>([]);

  useEffect(() => {
    bulk.presets().then(setPresets).catch((e) => toast(e.message));
  }, [toast]);

  if (view.kind === "setup")
    return (
      <Setup
        preset={view.preset}
        onBack={() => setView({ kind: "home" })}
        onStart={async (answers) => {
          const b = await bulk.create(view.preset.key, answers);
          setView({ kind: "batch", id: b.id });
        }}
      />
    );
  if (view.kind === "batch")
    return (
      <BatchView
        id={view.id}
        presets={presets}
        aiReady={aiReady}
        toast={toast}
        onExit={() => setView({ kind: "home" })}
        onSaved={(batch, items) => setView({ kind: "labels", batch, items })}
      />
    );
  if (view.kind === "labels")
    return <Labels batch={view.batch} items={view.items} onDone={() => setView({ kind: "home" })} />;

  return <Home presets={presets} toast={toast} onPick={(p) => setView({ kind: "setup", preset: p })} onOpen={(id) => setView({ kind: "batch", id })} />;
}

// ------------------------------------------------------------------ home

function Home({
  presets,
  toast,
  onPick,
  onOpen,
}: {
  presets: Preset[];
  toast: (m: string) => void;
  onPick: (p: Preset) => void;
  onOpen: (id: number) => void;
}) {
  const { shop } = useShop();
  const [open, setOpen] = useState<Batch[]>([]);
  useEffect(() => {
    bulk.open().then(setOpen).catch((e) => toast(e.message));
  }, [toast]);
  const ordered = [...presets].sort((a, b) => Number(b.key === shop.kind) - Number(a.key === shop.kind));

  return (
    <section>
      <h1>Bulk add</h1>
      <p className="muted">
        Got a box of 500 pieces? Lay them out on a tray, take a few photos, and StockSnap counts them, gives each one an
        ID and writes the descriptions.
      </p>
      {open.length > 0 && (
        <>
          <h2>Continue</h2>
          <ul className="list">
            {open.map((b) => (
              <li key={b.id}>
                <span>
                  Batch #{b.id} · {b.preset_label} · {b.progress.units} {b.mode === "unique" ? "pieces" : "units"}
                </span>
                <button className="btn btn-secondary" onClick={() => onOpen(b.id)}>Open</button>
              </li>
            ))}
          </ul>
        </>
      )}
      <h2>What are you adding?</h2>
      <div className="preset-grid">
        {ordered.map((p) => (
          <button key={p.key} className={`preset ${p.key === shop.kind ? "main" : ""}`} onClick={() => onPick(p)}>
            <strong>
              {p.label}
              {p.key === shop.kind && <span className="chip ok">Your main type</span>}
            </strong>
            <span className="muted small">
              {p.mode === "unique" ? "Every piece is different - each gets its own ID" : "Identical items are grouped and counted"}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------- setup

function Setup({
  preset,
  onBack,
  onStart,
}: {
  preset: Preset;
  onBack: () => void;
  onStart: (answers: Record<string, string>) => Promise<void>;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(preset.questions.filter((q) => q.kind === "select").map((q) => [q.key, q.options[0]])),
  );
  const [busy, setBusy] = useState(false);

  return (
    <section>
      <button className="link" onClick={onBack}>← Back</button>
      <h1>{preset.label}</h1>

      <div className="guide">
        <h2>Set up your photo</h2>
        <p>
          <strong>Background:</strong> {preset.background}
        </p>
        <ul>
          {preset.tips.map((t) => (
            <li key={t}>{t}</li>
          ))}
          <li>About {preset.per_photo} per photo.</li>
        </ul>
      </div>

      <h2>About this batch</h2>
      <p className="muted small">Answered once, applied to every item in this batch. Things the AI can't see from a photo belong here.</p>
      <form
        className="item-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onStart(answers);
          } finally {
            setBusy(false);
          }
        }}
      >
        {preset.questions.map((q) => (
          <label key={q.key}>
            {q.label}
            {q.kind === "select" ? (
              <select value={answers[q.key] ?? ""} onChange={(e) => setAnswers({ ...answers, [q.key]: e.target.value })}>
                {q.options.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                value={answers[q.key] ?? ""}
                inputMode={q.kind === "money" ? "decimal" : undefined}
                placeholder={q.kind === "money" ? "0.00" : ""}
                onChange={(e) => setAnswers({ ...answers, [q.key]: e.target.value })}
              />
            )}
            {q.help && <small>{q.help}</small>}
          </label>
        ))}
        <button className="btn btn-primary btn-big" disabled={busy}>
          Start batch
        </button>
      </form>
    </section>
  );
}

// ----------------------------------------------------------------- batch

function BatchView({
  id,
  presets,
  aiReady,
  toast,
  onExit,
  onSaved,
}: {
  id: number;
  presets: Preset[];
  aiReady: boolean;
  toast: (m: string) => void;
  onExit: () => void;
  onSaved: (b: Batch, items: Item[]) => void;
}) {
  const [b, setB] = useState<Batch | null>(null);
  const [uploading, setUploading] = useState(0);
  const [reviewing, setReviewing] = useState(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const refresh = useCallback(() => bulk.get(id).then(setB), [id]);
  useEffect(() => {
    refresh().catch((e) => toast(e.message));
  }, [refresh, toast]);

  // Poll while the AI works through the items.
  useEffect(() => {
    if (!b || !(b.describing || b.status === "describing")) return;
    const t = setInterval(() => refresh().catch(() => undefined), 2000);
    return () => clearInterval(t);
  }, [b, refresh]);

  useEffect(() => {
    if (b && (b.status === "describing" || b.status === "review")) setReviewing(true);
  }, [b]);

  if (!b) return <div className="hero"><span className="spinner big" /></div>;
  const preset = presets.find((p) => p.key === b.preset);

  // Photos upload one after another so numbering stays in order.
  function addPhoto(file: File) {
    setUploading((n) => n + 1);
    queue.current = queue.current
      .then(() => bulk.addPhoto(id, file))
      .then((nb) => {
        setB(nb);
        const last = nb.photos[nb.photos.length - 1];
        if (nb.warning) toast(nb.warning);
        else if (last) toast(`Found ${last.detections.length} on this photo`);
      })
      .catch((e) => toast((e as Error).message))
      .finally(() => setUploading((n) => n - 1));
  }

  async function describe() {
    setReviewing(true);
    if (!aiReady) return; // review without AI: type names yourself
    setB(await bulk.describe(id));
  }

  async function save() {
    try {
      const items = await bulk.save(id);
      onSaved(await bulk.get(id), items);
    } catch (e) {
      toast((e as Error).message);
    }
  }

  const answered = Object.entries(b.answers)
    .filter(([, v]) => v && !/^(mixed|not sure|none)/i.test(v))
    .map(([k, v]) => {
      const q = preset?.questions.find((qq) => qq.key === k);
      if (q?.kind === "money") return [k, `${q.field === "cost" ? "Cost" : "Price"} ${money(toCents(v) ?? 0)}`];
      return [k, v];
    });
  const live = b.groups.filter((g) => g.include);
  const working = b.describing || b.status === "describing";

  return (
    <section>
      <button className="link" onClick={onExit}>← All batches</button>
      <h1>
        Batch #{b.id} · {b.preset_label}
      </h1>
      {answered.length > 0 && (
        <p className="chips">
          {answered.map(([k, v]) => (
            <span key={k} className="chip">{v}</span>
          ))}
        </p>
      )}

      <div className="mini-stats">
        <span><strong data-testid="photos">{b.photos.length}</strong> {b.photos.length === 1 ? "photo" : "photos"}</span>
        <span><strong data-testid="pieces">{b.progress.pieces}</strong> pieces found</span>
        {b.mode === "identical" && <span><strong>{b.progress.groups}</strong> different products</span>}
        {reviewing && <span><strong>{b.progress.done}/{b.progress.groups}</strong> described</span>}
      </div>

      {!reviewing && (
        <>
          <div className="actions">
            <PhotoButton label={uploading ? `Uploading ${uploading}…` : "Photo of a tray"} onPhoto={addPhoto} />
            <PhotoButton label="Choose photos" onPhoto={addPhoto} multiple variant="secondary" />
          </div>
          {preset && (
            <details className="guide small">
              <summary>Photo tips</summary>
              <p><strong>Background:</strong> {preset.background}</p>
              <ul>{preset.tips.map((t) => <li key={t}>{t}</li>)}</ul>
            </details>
          )}
        </>
      )}

      {!reviewing &&
        b.photos.map((p) => (
          <TrayPhoto key={p.id} photo={p} onToggle={async (detId, include) => setB(await bulk.toggle(id, detId, include))} />
        ))}
      {!reviewing && b.photos.length > 0 && (
        <p className="muted small">Tap a box to remove something that isn't an item. Missed one? Take another photo of it.</p>
      )}

      {!reviewing && b.progress.pieces > 0 && (
        <div className="sticky-bar">
          <span>
            <strong>{b.progress.pieces}</strong> {b.mode === "unique" ? "pieces" : `units · ${b.progress.groups} products`}
          </span>
          <button className="btn btn-primary" onClick={describe} disabled={uploading > 0}>
            {aiReady ? "Next: describe with AI" : "Next: review"}
          </button>
        </div>
      )}

      {reviewing && (
        <>
          {working && (
            <div className="progress">
              <div className="progress-bar" style={{ width: `${(100 * b.progress.done) / Math.max(1, b.progress.groups)}%` }} />
              <span>
                <span className="spinner" /> Local AI is describing item {Math.min(b.progress.done + b.progress.failed + 1, b.progress.groups)} of{" "}
                {b.progress.groups}. You can review the finished ones now.
              </span>
            </div>
          )}
          {!aiReady && <div className="notice">Local AI is off, so type a name for each item (or leave blank for "{b.preset_label} #number").</div>}
          <BulkPrice batch={b} onChange={setB} />
          <div className="review">
            {b.groups.map((g) => (
              <GroupRow key={g.id} batch={b} group={g} onChange={setB} toast={toast} />
            ))}
          </div>
          <div className="sticky-bar">
            <span>
              <strong>{live.length}</strong> items
              {b.mode === "identical" && <> · <strong>{live.reduce((s, g) => s + g.count, 0)}</strong> units</>}
            </span>
            <button className="link" onClick={() => setReviewing(false)} disabled={working}>
              + photos
            </button>
            <button className="btn btn-primary" onClick={save} disabled={working}>
              Save to inventory
            </button>
          </div>
        </>
      )}

      <button
        className="link danger"
        onClick={async () => {
          if (!window.confirm("Discard this batch? Nothing has been added to inventory yet.")) return;
          await bulk.discard(id);
          onExit();
        }}
      >
        Discard batch
      </button>
    </section>
  );
}

function TrayPhoto({ photo, onToggle }: { photo: BatchPhoto; onToggle: (detId: number, include: boolean) => void }) {
  const fs = Math.max(18, photo.width / 45);
  return (
    <div className="tray">
      <svg viewBox={`0 0 ${photo.width} ${photo.height}`} role="img" aria-label={`${photo.detections.length} items found`}>
        <image href={imageUrl(photo.image_path)} width={photo.width} height={photo.height} />
        {photo.detections.map((d) => {
          const [x, y, w, h] = d.bbox;
          return (
            <g key={d.id} className={d.include ? "box" : "box off"} onClick={() => onToggle(d.id, !d.include)}>
              <rect x={x} y={y} width={w} height={h} rx={6} />
              <rect className="tagbg" x={x} y={y} width={fs * (String(d.number).length * 0.62 + 0.8)} height={fs * 1.3} rx={4} />
              <text x={x + fs * 0.4} y={y + fs * 1.0} fontSize={fs}>
                {d.number}
              </text>
            </g>
          );
        })}
      </svg>
      <span className="tray-count">{photo.detections.filter((d) => d.include).length} found</span>
    </div>
  );
}

function BulkPrice({ batch, onChange }: { batch: Batch; onChange: (b: Batch) => void }) {
  const cats = Array.from(new Set(batch.groups.filter((g) => g.include && g.category).map((g) => g.category)));
  const [cat, setCat] = useState("");
  const [price, setPrice] = useState("");
  return (
    <form
      className="bulk-price"
      onSubmit={async (e) => {
        e.preventDefault();
        const cents = toCents(price);
        if (!cents) return;
        onChange(await bulk.bulkEdit(batch.id, { price_cents: cents, category: cat || undefined }));
        setPrice("");
      }}
    >
      <span>Set price for</span>
      <select value={cat} onChange={(e) => setCat(e.target.value)}>
        <option value="">all items</option>
        {cats.map((c) => (
          <option key={c} value={c}>all {c}</option>
        ))}
      </select>
      <input value={price} onChange={(e) => setPrice(e.target.value)} placeholder="$" inputMode="decimal" />
      <button className="btn btn-secondary">Apply</button>
    </form>
  );
}

function GroupRow({
  batch,
  group: g,
  onChange,
  toast,
}: {
  batch: Batch;
  group: Group;
  onChange: (b: Batch) => void;
  toast: (m: string) => void;
}) {
  const [name, setName] = useState(g.name);
  const [price, setPrice] = useState(toDollars(g.price_cents));
  const [desc, setDesc] = useState(g.description);
  const [count, setCount] = useState(String(g.count));
  const [open, setOpen] = useState(false);

  // When the AI fills a row in, show it unless the seller already typed something.
  useEffect(() => setName((n) => n || g.name), [g.name]);
  useEffect(() => setDesc((d) => d || g.description), [g.description]);
  useEffect(() => setPrice(toDollars(g.price_cents)), [g.price_cents]);
  useEffect(() => setCount(String(g.count)), [g.count]);

  const update = async (data: Parameters<typeof bulk.updateGroup>[2]) => {
    try {
      onChange(await bulk.updateGroup(batch.id, g.id, data));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const nums = g.numbers.length > 4 ? `#${g.numbers.slice(0, 3).join(", #")}…` : `#${g.numbers.join(", #")}`;
  return (
    <div className={`group ${g.include ? "" : "excluded"}`}>
      <div className="group-photos">
        {g.crops.slice(0, batch.mode === "identical" ? 3 : 1).map((c) => (
          <img key={c} src={imageUrl(c)} alt="" />
        ))}
      </div>
      <div className="group-body">
        <div className="group-head">
          <span className="muted small">{nums}</span>
          {g.status === "pending" && batch.describing && <span className="chip"><span className="spinner" /> AI</span>}
          {g.status === "failed" && <span className="chip warn">AI couldn't read this - type a name</span>}
          {g.existing_item && (
            <span className="chip ok" title={`${g.existing_item.sku}, ${g.existing_item.quantity} in stock`}>
              Adds to {g.existing_item.sku}
            </span>
          )}
          <label className="check">
            <input type="checkbox" checked={g.include} onChange={(e) => update({ include: e.target.checked })} /> Keep
          </label>
        </div>
        <input
          className="group-name"
          value={name}
          placeholder={g.status === "pending" ? "Waiting for AI…" : "Name"}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name !== g.name && update({ name })}
        />
        <div className="group-fields">
          <label>
            Price $
            <input
              value={price}
              inputMode="decimal"
              onChange={(e) => setPrice(e.target.value)}
              onBlur={() => {
                const c = toCents(price);
                if (c !== null && c !== g.price_cents) update({ price_cents: c });
              }}
            />
          </label>
          {batch.mode === "identical" && (
            <label>
              Count
              <input
                value={count}
                inputMode="numeric"
                onChange={(e) => setCount(e.target.value)}
                onBlur={() => {
                  const n = Number(count);
                  if (Number.isInteger(n) && n >= 0 && n !== g.count) update({ count_override: n });
                }}
              />
            </label>
          )}
          <button type="button" className="link" onClick={() => setOpen(!open)}>
            {open ? "Less" : "Details"}
          </button>
        </div>
        {open && (
          <div className="group-details">
            <textarea value={desc} rows={2} onChange={(e) => setDesc(e.target.value)} onBlur={() => desc !== g.description && update({ description: desc })} />
            <p className="muted small">
              {[g.category, g.brand, g.material, g.color, g.size].filter(Boolean).join(" · ")}
              {g.tags && ` · ${g.tags}`}
            </p>
            {g.existing_item && (
              <button className="link" onClick={() => update({ add_to_existing: false })}>
                It's a different product - make a new item
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- labels

function Labels({ batch, items, onDone }: { batch: Batch; items: Item[]; onDone: () => void }) {
  const { shop } = useShop();
  const units = (it: Item) => batch.groups.find((g) => g.item?.id === it.id)?.count ?? 1;
  const numberOf = (it: Item) => batch.groups.find((g) => g.item?.id === it.id)?.numbers[0];
  const [perUnit, setPerUnit] = useState(batch.mode === "unique");
  const labels = items.flatMap((it) => Array.from({ length: perUnit ? units(it) : 1 }, () => it));

  return (
    <section>
      <div className="no-print">
        <h1>Saved ✓</h1>
        <p>
          {items.length} items added to inventory ({items.reduce((s, it) => s + units(it), 0)} units). Print the tags and attach
          them in tray order: label <strong>#1</strong> goes on piece #1.
        </p>
        <div className="actions">
          <button className="btn btn-primary btn-big" onClick={() => window.print()}>Print {labels.length} labels</button>
          <button className="btn btn-secondary" onClick={onDone}>Done</button>
        </div>
        {batch.mode === "identical" && (
          <label className="check">
            <input type="checkbox" checked={perUnit} onChange={(e) => setPerUnit(e.target.checked)} /> One label per unit (not per product)
          </label>
        )}
      </div>
      <div className="labels">
        {labels.map((it, i) => (
          <div className="label" key={`${it.id}-${i}`}>
            <div className="label-shop">{shop.name}</div>
            <div className="label-top">
              <span>#{numberOf(it)}</span>
              <strong>{money(it.price_cents)}</strong>
            </div>
            <img src={barcodeUrl(it.id)} alt={it.sku} />
            <div className="label-sku">{it.sku}</div>
            <div className="label-name">{it.name}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
