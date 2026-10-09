import { useEffect, useRef, useState } from "react";
import { KIND_LABELS, logoUrl, shops, type Shop, type ShopInput, type ShopKind } from "../api";

const KINDS = Object.keys(KIND_LABELS) as ShopKind[];

/**
 * Used three ways: first-run welcome, "+ New shop", and Shop settings (when
 * `existing` is given).
 */
export function ShopSetupPage({
  existing,
  first,
  onDone,
  onCancel,
  logoVersion = 0,
}: {
  existing?: Shop;
  first?: boolean;
  onDone: (shop: Shop) => void;
  onCancel?: () => void;
  logoVersion?: number;
}) {
  const [v, setV] = useState<ShopInput>({
    name: existing?.name ?? "",
    kind: existing?.kind ?? "clothing",
    sku_prefix: existing?.sku_prefix ?? "",
    low_stock_default: existing?.low_stock_default ?? 2,
    ai_context: existing?.ai_context ?? "",
  });
  const [prefixTouched, setPrefixTouched] = useState(!!existing);
  const [logo, setLogo] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>(existing ? logoUrl(existing, logoVersion) : "");
  const [removeLogo, setRemoveLogo] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // Suggest a SKU prefix from the name ("Sora in Bloom" -> SIB) until the user edits it.
  useEffect(() => {
    if (prefixTouched || !v.name.trim()) return;
    const t = setTimeout(() => {
      shops.suggestPrefix(v.name).then((r) => setV((cur) => ({ ...cur, sku_prefix: r.sku_prefix }))).catch(() => undefined);
    }, 250);
    return () => clearTimeout(t);
  }, [v.name, prefixTouched]);

  useEffect(() => {
    if (!logo) return;
    const url = URL.createObjectURL(logo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [logo]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!v.name.trim()) return setError("Give your shop a name.");
    setError("");
    setSaving(true);
    try {
      let shop = existing ? await shops.update(existing.slug, v) : await shops.create(v);
      if (logo) shop = await shops.uploadLogo(shop.slug, logo);
      else if (removeLogo && existing?.has_logo) shop = await shops.removeLogo(shop.slug);
      onDone(shop);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const exampleSku = `${v.sku_prefix || "TSH"}-00012${v.kind === "clothing" ? "-M" : ""}`;

  return (
    <section className={first ? "setup first" : "setup"}>
      {first ? (
        <div className="welcome">
          <img src="/icon.svg" alt="" width={56} height={56} />
          <h1>Welcome to StockSnap</h1>
          <p className="muted">
            Let's set up your shop. It takes a minute, everything stays on this computer, and you can add more shops later,
            for example one for clothing and one for jewellery.
          </p>
        </div>
      ) : (
        <>
          {onCancel && <button className="link" onClick={onCancel}>← Back</button>}
          <h1>{existing ? "Shop settings" : "New shop"}</h1>
          {!existing && <p className="muted">Each shop has its own inventory, sales and reports.</p>}
        </>
      )}

      <form className="item-form" onSubmit={submit}>
        <label>
          Shop or brand name
          <input
            value={v.name}
            onChange={(e) => setV({ ...v, name: e.target.value })}
            placeholder="e.g. Sora in Bloom"
            autoFocus={!existing}
            maxLength={80}
          />
          <small>Shown at the top of the app, on price tags and reports.</small>
        </label>

        <fieldset className="kinds">
          <legend>What do you mainly sell?</legend>
          {KINDS.map((k) => (
            <label key={k} className={`kind ${v.kind === k ? "on" : ""}`}>
              <input type="radio" name="kind" value={k} checked={v.kind === k} onChange={() => setV({ ...v, kind: k })} />
              <strong>{KIND_LABELS[k].label}</strong>
              <span className="muted small">{KIND_LABELS[k].hint}</span>
            </label>
          ))}
          <small className="muted">Sets your categories and the first bulk-add type. You can still add anything.</small>
        </fieldset>

        <label>
          Describe what you sell <span className="muted small">(optional, helps the AI)</span>
          <textarea
            rows={2}
            maxLength={400}
            value={v.ai_context}
            onChange={(e) => setV({ ...v, ai_context: e.target.value })}
            placeholder="In your own words, e.g. Hand-embroidered outfits and crowns for small statues"
          />
          <small>The AI reads this before every photo, so it names things the way you would.</small>
        </label>

        <div className="row2">
          <label>
            SKU prefix
            <input
              value={v.sku_prefix}
              onChange={(e) => {
                setPrefixTouched(true);
                setV({ ...v, sku_prefix: e.target.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 6) });
              }}
              placeholder="SIB"
            />
            <small>New items get codes like {exampleSku}</small>
          </label>
          <label>
            Warn me when stock is at
            <input
              type="number"
              min={0}
              value={v.low_stock_default}
              onChange={(e) => setV({ ...v, low_stock_default: Math.max(0, Number(e.target.value) || 0) })}
            />
            <small>Items at or below this show as "running low".</small>
          </label>
        </div>

        <div className="logo-row">
          <div className="logo-preview">{preview && !removeLogo ? <img src={preview} alt="Logo" /> : <span>Logo</span>}</div>
          <div>
            <strong>Logo</strong> <span className="muted small">(optional)</span>
            <div className="actions">
              <button type="button" className="btn btn-secondary" onClick={() => fileInput.current?.click()}>
                {preview && !removeLogo ? "Change logo" : "Add logo"}
              </button>
              {preview && !removeLogo && (
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    setLogo(null);
                    setPreview("");
                    setRemoveLogo(true);
                  }}
                >
                  Remove
                </button>
              )}
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setLogo(f);
                  setRemoveLogo(false);
                }
                e.target.value = "";
              }}
            />
          </div>
        </div>

        {error && <p className="error">{error}</p>}
        <div className="actions">
          {onCancel && !first && (
            <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          )}
          <button className="btn btn-primary btn-big" disabled={saving}>
            {saving ? "Saving…" : existing ? "Save settings" : first ? "Create my shop" : "Create shop"}
          </button>
        </div>
      </form>

      {existing && (
        <div className="guide small">
          <h2>Your data</h2>
          <p>
            This shop's items, sales and photos are kept in their own folder on this computer
            (<code>.stocksnap/shops/{existing.slug}</code> in your user folder).
          </p>
          <div className="actions">
            <a className="btn btn-secondary" href="/api/backup">Download a backup (.zip)</a>
            <a className="btn btn-secondary" href="/api/items/export.csv">Inventory CSV</a>
          </div>
        </div>
      )}
    </section>
  );
}
