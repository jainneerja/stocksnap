import type { Facet } from "../api";

/** Horizontal, scrollable filter chips: "All 248 · Earrings 212 · Rings 96 …" */
export function CategoryChips({
  facets,
  total,
  value,
  onChange,
}: {
  facets: Facet[];
  total: number;
  value: string;
  onChange: (category: string) => void;
}) {
  if (facets.length === 0) return null;
  return (
    <div className="chip-row" role="tablist" aria-label="Categories">
      <button role="tab" aria-selected={value === ""} className={`fchip ${value === "" ? "on" : ""}`} onClick={() => onChange("")}>
        All <span>{total}</span>
      </button>
      {facets.map((f) => (
        <button
          key={f.name}
          role="tab"
          aria-selected={value === f.name}
          className={`fchip ${value === f.name ? "on" : ""}`}
          onClick={() => onChange(value === f.name ? "" : f.name)}
        >
          {f.name} <span>{f.items}</span>
        </button>
      ))}
    </div>
  );
}
