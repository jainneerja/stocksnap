import { useCallback, useEffect, useRef, useState } from "react";
import { catalogues, type Catalogue, type CatalogueItem, type CatalogueSummary } from "../api";
import { useShop } from "../shop";

const IMAGE = /\.(jpe?g|png|webp|heic|heif|bmp)$/i;

/**
 * Product catalogue: pick a folder of product photos (one photo per product),
 * the app writes names and descriptions, the seller adds prices, and gets a PDF
 * to send on WhatsApp or print.
 */
export function CataloguePage({ toast }: { toast: (m: string) => void }) {
  const { shop } = useShop();
  const [recent, setRecent] = useState<CatalogueSummary[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState(`${shop.name} catalogue`);
  const [hint, setHint] = useState("");
  const [clean, setClean] = useState(false);
  const [describe, setDescribe] = useState(true);
  const [busy, setBusy] = useState(false);
  const [cat, setCat] = useState<Catalogue | null>(null);
  const [dirty, setDirty] = useState(false);
  const [allPrice, setAllPrice] = useState("");
  const folderInput = useRef<HTMLInputElement>(null);

  const loadRecent = useCallback(() => catalogues.list().then(setRecent).catch(() => undefined), []);
  useEffect(() => { loadRecent(); }, [loadRecent]);

  // folder pickers need these non-standard attributes
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
    folderInput.current?.setAttribute("directory", "");
  }, []);

  // while names are being written, refresh (but never overwrite what the seller typed)
  useEffect(() => {
    if (!cat || cat.status === "done") return;
    const t = setInterval(async () => {
      try {
        const fresh = await catalogues.get(cat.id);
        setCat((c) => (c && c.id === fresh.id ? mergeFresh(c, fresh, dirty) : c));
      } catch {
        /* keep trying */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [cat, dirty]);

  function pick(list: FileList | null) {
    const rel = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
    const photos = Array.from(list ?? []).filter((f) =>
      (IMAGE.test(f.name) || f.type.startsWith("image/")) &&
      !rel(f).split("/").slice(0, -1).some((p) => p.startsWith("_") || p.startsWith(".")));
    photos.sort((a, b) => rel(a).localeCompare(rel(b), undefined, { numeric: true }));
    setFiles(photos);
    if (list?.length && !photos.length) toast("No photos in that folder (JPG or PNG).");
  }

  async function start() {
    setBusy(true);
    try {
      const c = await catalogues.create(files, { title, hint, clean_background: clean, describe });
      setCat(c);
      setDirty(false);
      setFiles([]);
      loadRecent();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    try {
      setCat(await catalogues.get(id));
      setDirty(false);
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function save(): Promise<boolean> {
    if (!cat) return false;
    try {
      const saved = await catalogues.update(cat.id, {
        title: cat.title, subtitle: cat.subtitle, columns: cat.columns, layout: cat.layout, product: cat.product,
        items: cat.items.map(({ id, name, description, price, code, include, colour }) => ({ id, name, description, price, code, include, colour })),
      });
      setCat(saved);
      setDirty(false);
      return true;
    } catch (e) {
      toast((e as Error).message);
      return false;
    }
  }

  async function download() {
    if (dirty && !(await save())) return;
    window.location.href = catalogues.pdfUrl(cat!.id);
  }

  async function remove() {
    if (!cat || !confirm(`Delete "${cat.title}"? Your photos in the folder are not touched.`)) return;
    await catalogues.remove(cat.id).catch(() => undefined);
    setCat(null);
    loadRecent();
  }

  const edit = (patch: Partial<Catalogue>) => { setCat((c) => (c ? { ...c, ...patch } : c)); setDirty(true); };
  const editItem = (id: number, patch: Partial<CatalogueItem>) => {
    setCat((c) => (c ? { ...c, items: c.items.map((it) => (it.id === id ? { ...it, ...patch } : it)) } : c));
    setDirty(true);
  };

  if (cat) {
    const included = cat.items.filter((it) => it.include && it.status !== "failed").length;
    return (
      <section>
        <div className="page-head">
          <h1>{cat.title || "Catalogue"}</h1>
          <button className="link" onClick={() => { setCat(null); loadRecent(); }}>← All catalogues</button>
        </div>

        {cat.status !== "done" && (
          <div className="progress">
            <div className="progress-bar" style={{ width: `${(100 * cat.done) / Math.max(1, cat.total)}%` }} />
            <span><span className="spinner" /> Writing names and descriptions: {cat.done} of {cat.total}… You can add prices meanwhile.</span>
          </div>
        )}
        {cat.status === "done" && cat.mode && (
          <p className="muted small">Names written with {cat.mode === "instant" ? "templates (no AI)" : `${cat.mode} AI`}. Check them before sharing.</p>
        )}
        {cat.notes.map((n) => <p key={n} className="muted small">{n}</p>)}

        <div className="cat-settings">
          <label>Title<input value={cat.title} onChange={(e) => edit({ title: e.target.value })} maxLength={100} /></label>
          <label>Line under the title (contact, offer…)
            <input value={cat.subtitle} placeholder="Order on WhatsApp: +91 …" onChange={(e) => edit({ subtitle: e.target.value })} maxLength={200} />
          </label>
          <div className="cat-row">
            <span className="small">Layout</span>
            <div className="seg" role="group" aria-label="Layout">
              <button className={cat.layout === "designs" ? "on" : ""} onClick={() => edit({ layout: "designs" })}>By design (colours together)</button>
              <button className={cat.layout === "grid" ? "on" : ""} onClick={() => edit({ layout: "grid" })}>One card per photo</button>
            </div>
          </div>
          {cat.layout === "designs" && (
            <label>Product name in headings
              <input value={cat.product} placeholder="e.g. Lehenga patka" onChange={(e) => edit({ product: e.target.value })} maxLength={80} />
            </label>
          )}
          <div className="cat-row">
            <span className="small">{cat.layout === "designs" ? "Photos per row" : "Per page"}</span>
            <div className="seg" role="group" aria-label="Products per page">
              <button className={cat.columns === 2 ? "on" : ""} onClick={() => edit({ columns: 2 })}>{cat.layout === "designs" ? "2" : "4 big"}</button>
              <button className={cat.columns === 3 ? "on" : ""} onClick={() => edit({ columns: 3 })}>{cat.layout === "designs" ? "3" : "9 small"}</button>
            </div>
          </div>
          <div className="bulk-price">
            Price for all
            <input style={{ width: 110 }} value={allPrice} placeholder="₹499" onChange={(e) => setAllPrice(e.target.value)} />
            <button className="btn btn-secondary" disabled={!allPrice.trim()}
              onClick={() => { setCat((c) => (c ? { ...c, items: c.items.map((it) => ({ ...it, price: allPrice.trim() })) } : c)); setDirty(true); }}>
              Apply
            </button>
          </div>
        </div>

        <ul className="cat-items">
          {cat.items.map((it) => (
            <li key={it.id} className={`cat-item ${it.include ? "" : "off"}`}>
              <img src={catalogues.photoUrl(cat.id, it.photo)} alt="" loading="lazy" />
              <div className="cat-fields">
                <input aria-label="Name" value={it.name} placeholder={it.status === "queued" ? "Writing…" : "Name"}
                  onChange={(e) => editItem(it.id, { name: e.target.value })} maxLength={120} />
                <div className="cat-row">
                  <input aria-label="Price" className="cat-price" value={it.price} placeholder="Price"
                    onChange={(e) => editItem(it.id, { price: e.target.value })} maxLength={30} />
                  <input aria-label="Code" className="cat-code" value={it.code} placeholder="Code"
                    onChange={(e) => editItem(it.id, { code: e.target.value })} maxLength={30} />
                  {cat.layout === "designs" && (
                    <input aria-label="Colour" className="cat-code" value={it.colour ?? ""} placeholder="Colour"
                      onChange={(e) => editItem(it.id, { colour: e.target.value })} maxLength={40} />
                  )}
                </div>
                <textarea aria-label="Description" rows={2} value={it.description}
                  placeholder={it.status === "queued" ? "Writing…" : "Short description (optional)"}
                  onChange={(e) => editItem(it.id, { description: e.target.value })} maxLength={600} />
                <label className="check small">
                  <input type="checkbox" checked={it.include} onChange={(e) => editItem(it.id, { include: e.target.checked })} />
                  In catalogue <span className="muted">· {[it.design, it.size && `Size ${it.size}`, it.colour].filter(Boolean).join(" · ") || it.file}</span>
                  {it.status === "failed" && <span className="error"> couldn't read this photo</span>}
                </label>
              </div>
            </li>
          ))}
        </ul>

        <div className="sticky-bar">
          <span className="small muted">{included} in catalogue</span>
          <button className="link small" onClick={remove}>Delete</button>
          <button className="btn btn-secondary" disabled={!dirty} onClick={save}>Save</button>
          <button className="btn btn-primary" disabled={!included} onClick={download}>Download PDF</button>
        </div>
      </section>
    );
  }

  return (
    <section>
      <div className="page-head">
        <h1>Catalogue</h1>
        <span className="muted small">Product photos → a PDF to share or print</span>
      </div>

      <div className="item-form">
        <p className="muted small" style={{ margin: 0 }}>
          Put one photo per product in a folder on this computer (the file name can be the product name,
          e.g. <em>red-leaves-dress.jpg</em>). Or sort them in folders like <em>Size 7 / Design 2 / Red.jpg</em>:
          the catalogue then shows each design with all its colours. Pick the folder: the photos stay where they are,
          the app keeps its own copy.
        </p>
        <div className="actions" style={{ marginTop: 0 }}>
          <label className="btn btn-primary">
            Choose folder
            <input ref={folderInput} type="file" multiple hidden onChange={(e) => pick(e.target.files)} />
          </label>
          <label className="btn btn-secondary">
            Or choose photos
            <input type="file" accept="image/*" multiple hidden onChange={(e) => pick(e.target.files)} />
          </label>
        </div>
        {files.length > 0 && (
          <>
            <p className="notice">{files.length} photo{files.length === 1 ? "" : "s"} picked: {files.slice(0, 4).map((f) => f.name).join(", ")}{files.length > 4 ? "…" : ""}</p>
            <label>Catalogue title<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} /></label>
            <label>What are these? <span className="muted small">(helps the AI name them)</span>
              <input value={hint} placeholder="e.g. Laddu Gopal dresses" onChange={(e) => setHint(e.target.value)} maxLength={120} />
            </label>
            <label className="check"><input type="checkbox" checked={describe} onChange={(e) => setDescribe(e.target.checked)} /> Write names and descriptions for me</label>
            <label className="check"><input type="checkbox" checked={clean} onChange={(e) => setClean(e.target.checked)} /> Clean white background (cut the product out)</label>
            <div className="actions">
              <button className="btn btn-primary btn-big" disabled={busy} onClick={start}>
                {busy ? <><span className="spinner" /> Uploading…</> : `Make catalogue from ${files.length} photos`}
              </button>
            </div>
          </>
        )}
      </div>

      {recent.length > 0 && (
        <>
          <h2>Your catalogues</h2>
          <div className="lab-recent">
            {recent.map((r) => (
              <button key={r.id} className="lab-thumb" onClick={() => open(r.id)}>
                {r.cover && <img src={catalogues.photoUrl(r.id, r.cover)} alt="" />}
                <span className="small">{r.title}</span>
                <span className="small muted">{r.total} products</span>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

/** New server data, but keep what the seller is typing. */
function mergeFresh(local: Catalogue, fresh: Catalogue, dirty: boolean): Catalogue {
  if (!dirty) return fresh;
  return {
    ...fresh, title: local.title, subtitle: local.subtitle, columns: local.columns, layout: local.layout, product: local.product,
    items: fresh.items.map((f) => {
      const l = local.items.find((x) => x.id === f.id);
      if (!l) return f;
      return {
        ...f,
        price: l.price, code: l.code, include: l.include, colour: l.colour || f.colour,
        name: l.name !== "" ? l.name : f.name,
        description: l.description !== "" ? l.description : f.description,
      };
    }),
  };
}
