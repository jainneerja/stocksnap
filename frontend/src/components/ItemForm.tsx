import { useEffect, useState } from "react";
import { api, imageUrl, type Item, type ItemInput } from "../api";
import { toCents, toDollars } from "../format";

export interface FormValues {
  name: string;
  category: string;
  description: string;
  tags: string;
  color: string;
  size: string;
  material: string;
  barcode: string;
  sku: string;
  cost: string;
  price: string;
  quantity: string;
}

export const emptyForm: FormValues = {
  name: "", category: "", description: "", tags: "", color: "", size: "",
  material: "", barcode: "", sku: "", cost: "", price: "", quantity: "1",
};

export function formFromItem(i: Item): FormValues {
  return {
    name: i.name, category: i.category, description: i.description, tags: i.tags,
    color: i.color, size: i.size, material: i.material, barcode: i.barcode ?? "",
    sku: i.sku, cost: toDollars(i.cost_cents), price: toDollars(i.price_cents),
    quantity: String(i.quantity),
  };
}

const norm = (t: string) => t.trim().replace(/\s+/g, " ").toLowerCase();

export function ItemForm({
  initial,
  imagePath,
  tagImagePath,
  aiBusy,
  submitLabel,
  onSubmit,
  onCancel,
  onAddStock,
  editingId,
}: {
  initial: FormValues;
  imagePath?: string | null;
  tagImagePath?: string | null;
  aiBusy?: boolean;
  submitLabel: string;
  onSubmit: (data: ItemInput) => Promise<void>;
  onCancel?: () => void;
  /** When set, the form warns about an existing item with the same name + size. */
  onAddStock?: (item: Item) => void;
  editingId?: number;
}) {
  const [v, setV] = useState(initial);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [more, setMore] = useState(false);

  // When the AI draft arrives, only fill fields the user hasn't typed in.
  const [lastInitial, setLastInitial] = useState(initial);
  if (initial !== lastInitial) {
    setLastInitial(initial);
    setV((cur) => {
      const next = { ...cur };
      (Object.keys(initial) as (keyof FormValues)[]).forEach((k) => {
        if (!cur[k] || cur[k] === lastInitial[k]) next[k] = initial[k];
      });
      return next;
    });
  }

  // Other sizes of the same product already in inventory (matched by name).
  const [siblings, setSiblings] = useState<Item[]>([]);
  useEffect(() => {
    const name = norm(v.name);
    if (!name) return setSiblings([]);
    const t = setTimeout(() => {
      api
        .items(v.name.trim())
        .then((all) => setSiblings(all.filter((i) => norm(i.name) === name && i.id !== editingId)))
        .catch(() => setSiblings([]));
    }, 300);
    return () => clearTimeout(t);
  }, [v.name, editingId]);
  const sameSize = v.size.trim() ? siblings.find((i) => norm(i.size) === norm(v.size)) : undefined;
  const otherSizes = siblings.filter((i) => i.size && i !== sameSize);

  const set = (k: keyof FormValues) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setV({ ...v, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const cost = toCents(v.cost);
    const price = toCents(v.price);
    const qty = Number(v.quantity || 0);
    if (!v.name.trim()) return setError("Please give the item a name.");
    if (cost === null || price === null) return setError("Prices should be numbers, like 12.50");
    if (!Number.isInteger(qty)) return setError("Quantity should be a whole number.");
    setError("");
    setSaving(true);
    try {
      await onSubmit({
        name: v.name.trim(), category: v.category.trim(), description: v.description.trim(),
        tags: v.tags.trim(), color: v.color.trim(), size: v.size.trim(), material: v.material.trim(),
        barcode: v.barcode.trim() || null, sku: v.sku.trim() || undefined,
        cost_cents: cost, price_cents: price, quantity: qty,
        image_path: imagePath ?? undefined,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="item-form" onSubmit={submit}>
      {(imagePath || tagImagePath) && (
        <div className="form-photos">
          {imagePath && <img className="form-photo" src={imageUrl(imagePath)} alt="Product" />}
          {tagImagePath && <img className="form-photo tag" src={imageUrl(tagImagePath)} alt="Size tag" />}
        </div>
      )}
      {aiBusy && (
        <p className="ai-note">
          <span className="spinner" /> Local AI is writing a description… you can start typing.
        </p>
      )}
      <div className="name-size">
        <label>
          Name
          <input value={v.name} onChange={set("name")} placeholder="e.g. Rhododendron tee" autoFocus />
        </label>
        <label>
          Size
          <input value={v.size} onChange={set("size")} placeholder="M, 8 oz…" />
        </label>
      </div>
      <div className="row3">
        <label>
          Price $
          <input value={v.price} onChange={set("price")} inputMode="decimal" placeholder="25.00" />
        </label>
        <label>
          Cost $
          <input value={v.cost} onChange={set("cost")} inputMode="decimal" placeholder="9.00" />
        </label>
        <label>
          In stock
          <input value={v.quantity} onChange={set("quantity")} inputMode="numeric" />
        </label>
      </div>
      <label>
        Description
        <textarea value={v.description} onChange={set("description")} rows={3} />
      </label>
      <label>
        Category
        <input value={v.category} onChange={set("category")} placeholder="T-shirt" />
      </label>
      <button type="button" className="link" onClick={() => setMore(!more)}>
        {more ? "Fewer details" : "More details (tags, colour, barcode, SKU)"}
      </button>
      {more && (
        <>
          <label>
            Tags <small>(comma separated)</small>
            <input value={v.tags} onChange={set("tags")} />
          </label>
          <div className="row2">
            <label>
              Colour
              <input value={v.color} onChange={set("color")} />
            </label>
            <label>
              Material
              <input value={v.material} onChange={set("material")} />
            </label>
          </div>
          <div className="row2">
            <label>
              Barcode
              <input value={v.barcode} onChange={set("barcode")} />
            </label>
            <label>
              SKU <small>(auto if blank)</small>
              <input value={v.sku} onChange={set("sku")} />
            </label>
          </div>
        </>
      )}
      {sameSize && (
        <div className="notice warn">
          You already have <strong>{sameSize.name}</strong> in size <strong>{sameSize.size}</strong> (
          {sameSize.quantity} in stock).
          {onAddStock && (
            <button type="button" className="btn btn-primary" onClick={() => onAddStock(sameSize)}>
              Add 1 to that item instead
            </button>
          )}
        </div>
      )}
      {!sameSize && otherSizes.length > 0 && (
        <div className="notice">
          Also in stock: {otherSizes.map((i) => `${i.size} (${i.quantity})`).join(", ")}.{" "}
          {v.size.trim() ? `This will be saved as size ${v.size.trim()}.` : "Add a size so this is saved as a separate size."}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="actions">
        {onCancel && (
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button className="btn btn-primary btn-big" disabled={saving}>
          {saving ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
