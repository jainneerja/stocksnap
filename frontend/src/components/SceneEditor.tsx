import { useEffect, useRef, useState } from "react";
import { scenes, type Scene, type Stroke } from "../api";
import { PhotoButton } from "./PhotoButton";

type Tool = "shape" | "keep" | "erase";
type Drag =
  | { kind: "oval-move" | "oval-rx" | "oval-top" | "oval-bottom" | "box-move" | "box-tl" | "box-br"; x: number; y: number; orig: Geo }
  | null;

interface Geo {
  cx: number;
  top: number;
  bottom: number;
  rx: number;
  tilt: number;
  scale: number;
  top_box: [number, number, number, number] | null;
}

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));

/**
 * Turn any nice photo into a reusable scene:
 *  1. drag the oval over where the product lies (and the box over the chest, if the product has a top piece)
 *  2. "Check" shows what the app worked out: blue = replaced, green = kept on top
 *  3. brush "Keep" over hands/jewellery it missed, "Erase" over leftovers of the old product
 *  4. try it with a real product photo
 */
export function SceneEditor({
  scene,
  onSaved,
  onClose,
  onDelete,
  toast,
}: {
  scene: Scene;
  onSaved: (s: Scene) => void;
  onClose: () => void;
  onDelete: () => void;
  toast: (m: string) => void;
}) {
  const [geo, setGeo] = useState<Geo>({
    cx: scene.cx, top: scene.top, bottom: scene.bottom, rx: scene.rx, tilt: scene.tilt, scale: scene.scale ?? 1, top_box: scene.top_box,
  });
  const [keep, setKeep] = useState<Stroke[]>(scene.keep);
  const [erase, setErase] = useState<Stroke[]>(scene.remove);
  const [tool, setTool] = useState<Tool>("shape");
  const [brush, setBrush] = useState(0.025);
  const [view, setView] = useState<"scene" | "layers">("scene");
  const [version, setVersion] = useState(0);
  const [name, setName] = useState(scene.name);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [product, setProduct] = useState<File | null>(null);
  const [result, setResult] = useState("");
  const [trying, setTrying] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag>(null);
  const drawing = useRef<Stroke | null>(null);
  const [live, setLive] = useState<Stroke | null>(null);

  const W = scene.width;
  const H = scene.height;
  const aspect = H / W;

  useEffect(() => () => { if (result) URL.revokeObjectURL(result); }, [result]);

  function pos(e: React.PointerEvent): [number, number] {
    const r = svg.current!.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  }

  function startDrag(kind: NonNullable<Drag>["kind"]) {
    return (e: React.PointerEvent) => {
      if (tool !== "shape") return;
      e.stopPropagation();
      e.preventDefault(); // no text selection while dragging
      (e.target as Element).setPointerCapture?.(e.pointerId);
      const [x, y] = pos(e);
      drag.current = { kind, x, y, orig: { ...geo, top_box: geo.top_box ? [...geo.top_box] : null } };
    };
  }

  function onDown(e: React.PointerEvent) {
    if (tool === "shape") return;
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const [x, y] = pos(e);
    drawing.current = { points: [[x, y]], r: brush };
    setLive(drawing.current);
  }

  function onMove(e: React.PointerEvent) {
    const [x, y] = pos(e);
    if (drawing.current) {
      const pts = drawing.current.points;
      const [lx, ly] = pts[pts.length - 1];
      if (Math.hypot(x - lx, (y - ly) * aspect) > brush / 3) {
        drawing.current = { ...drawing.current, points: [...pts, [x, y]] };
        setLive(drawing.current);
      }
      return;
    }
    const d = drag.current;
    if (!d) return;
    const dx = x - d.x;
    const dy = y - d.y;
    const o = d.orig;
    const g: Geo = { ...o, top_box: o.top_box ? [...o.top_box] : null };
    if (d.kind === "oval-move") {
      g.cx = clamp(o.cx + dx);
      const span = o.bottom - o.top;
      g.top = clamp(o.top + dy, 0, 1 - span);
      g.bottom = g.top + span;
    } else if (d.kind === "oval-rx") g.rx = clamp(Math.abs(x - o.cx), 0.05, 0.7);
    else if (d.kind === "oval-top") g.top = clamp(y, 0, o.bottom - 0.06);
    else if (d.kind === "oval-bottom") g.bottom = clamp(y, o.top + 0.06, 1);
    else if (o.top_box && g.top_box) {
      const [x0, y0, x1, y1] = o.top_box;
      if (d.kind === "box-move") {
        const bw = x1 - x0, bh = y1 - y0;
        const nx = clamp(x0 + dx, 0, 1 - bw), ny = clamp(y0 + dy, 0, 1 - bh);
        g.top_box = [nx, ny, nx + bw, ny + bh];
      } else if (d.kind === "box-tl") g.top_box = [Math.min(x, x1 - 0.04), Math.min(y, y1 - 0.04), x1, y1];
      else if (d.kind === "box-br") g.top_box = [x0, y0, Math.max(x, x0 + 0.04), Math.max(y, y0 + 0.04)];
    }
    setGeo(g);
    setDirty(true);
  }

  function onUp() {
    drag.current = null;
    if (drawing.current) {
      const s = drawing.current;
      drawing.current = null;
      setLive(null);
      if (tool === "keep") setKeep((k) => [...k, s]);
      else setErase((r) => [...r, s]);
      setDirty(true);
    }
  }

  async function save(): Promise<Scene | null> {
    setSaving(true);
    try {
      const s = await scenes.update(scene.id, { ...geo, top_box: geo.top_box ?? [], keep, remove: erase, name });
      setVersion((v) => v + 1);
      setDirty(false);
      onSaved(s);
      return s;
    } catch (e) {
      toast((e as Error).message);
      return null;
    } finally {
      setSaving(false);
    }
  }

  const [checked, setChecked] = useState(false);

  // One loop: save, show what was found, and (if a product was tried) show it again.
  async function check() {
    if (!(await save())) return;
    setView("layers");
    setChecked(true);
    if (product) await render(product);
  }

  async function tryWith(file: File | null) {
    if (!file) return;
    setProduct(file);
    if (dirty && !(await save())) return;
    await render(file);
  }

  async function render(file: File) {
    setTrying(true);
    try {
      const url = await scenes.tryOn(scene.id, { file });
      setResult((old) => {
        if (old) URL.revokeObjectURL(old);
        return url;
      });
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setTrying(false);
    }
  }

  const cy = ((geo.top + geo.bottom) / 2) * H;
  const ry = ((geo.bottom - geo.top) / 2) * H;
  const handle = 0.018 * W;
  const box = geo.top_box;
  const strokePath = (s: Stroke) => s.points.map(([x, y], i) => `${i ? "L" : "M"}${x * W},${y * H}`).join(" ");

  return (
    <section className="scene-editor">
      <button className="link" onClick={onClose}>← Photos</button>
      <div className="page-head">
        <input className="scene-name" value={name} maxLength={60} onChange={(e) => { setName(e.target.value); setDirty(true); }} aria-label="Scene name" />
      </div>

      <ol className="steps small muted">
        <li><strong>Shape:</strong> drag the oval over where the product lies. Turn on the top-piece box for dresses with a bodice.</li>
        <li><strong>Check</strong> what the app found: <span className="sw blue" /> replaced, <span className="sw green" /> kept on top.</li>
        <li>Brush <strong>Keep</strong> over hands or jewellery it missed, <strong>Erase</strong> over bits of the old product.</li>
        <li><strong>Try</strong> it with a real product photo.</li>
      </ol>

      <div className="scene-tools">
        <div className="seg" role="group" aria-label="Tool">
          {(["shape", "keep", "erase"] as Tool[]).map((t) => (
            <button key={t} className={tool === t ? "on" : ""} onClick={() => setTool(t)}>
              {t === "shape" ? "Shape" : t === "keep" ? "Keep brush" : "Erase brush"}
            </button>
          ))}
        </div>
        {tool !== "shape" && (
          <label className="inline small">
            Size
            <input type="range" min={0.008} max={0.08} step={0.002} value={brush} onChange={(e) => setBrush(Number(e.target.value))} />
          </label>
        )}
        {tool === "shape" && (
          <label className="check small">
            <input
              type="checkbox"
              checked={!!box}
              onChange={(e) => {
                setDirty(true);
                setGeo((g) => ({
                  ...g,
                  top_box: e.target.checked
                    ? [g.cx - g.rx * 0.3, Math.max(0, g.top + 0.01), g.cx + g.rx * 0.3, (g.top + g.bottom) / 2 - 0.05]
                    : null,
                }));
              }}
            />
            Top piece (bodice)
          </label>
        )}
        <button className="link small" disabled={!keep.length && !erase.length}
          onClick={() => { tool === "erase" ? setErase((r) => r.slice(0, -1)) : setKeep((k) => k.slice(0, -1)); setDirty(true); }}>
          Undo stroke
        </button>
        <div className="seg" role="group" aria-label="View">
          <button className={view === "scene" ? "on" : ""} onClick={() => setView("scene")}>Photo</button>
          <button className={view === "layers" ? "on" : ""} onClick={() => setView("layers")} disabled={dirty}>Layers</button>
        </div>
      </div>

      <div className="scene-work">
      <div className={`scene-canvas tool-${tool}`}>
        <img src={scenes.fileUrl(scene.id, view === "layers" ? "layers.jpg" : "scene.jpg", version)} alt="" draggable={false} />
        <svg
          ref={svg}
          viewBox={`0 0 ${W} ${H}`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
        >
          {keep.map((s, i) => <path key={`k${i}`} d={strokePath(s)} className="stroke keep" strokeWidth={s.r * 2 * W} />)}
          {erase.map((s, i) => <path key={`e${i}`} d={strokePath(s)} className="stroke erase" strokeWidth={s.r * 2 * W} />)}
          {live && <path d={strokePath(live)} className={`stroke ${tool}`} strokeWidth={live.r * 2 * W} />}
          <ellipse cx={geo.cx * W} cy={cy} rx={geo.rx * W} ry={ry} className="oval" onPointerDown={startDrag("oval-move")} />
          {box && (
            <rect x={box[0] * W} y={box[1] * H} width={(box[2] - box[0]) * W} height={(box[3] - box[1]) * H} className="topbox"
              onPointerDown={startDrag("box-move")} />
          )}
          {tool === "shape" && (
            <g className="handles">
              <circle cx={(geo.cx + geo.rx) * W} cy={cy} r={handle} onPointerDown={startDrag("oval-rx")} />
              <circle cx={geo.cx * W} cy={geo.top * H} r={handle} onPointerDown={startDrag("oval-top")} />
              <circle cx={geo.cx * W} cy={geo.bottom * H} r={handle} onPointerDown={startDrag("oval-bottom")} />
              {box && <circle cx={box[0] * W} cy={box[1] * H} r={handle} onPointerDown={startDrag("box-tl")} />}
              {box && <circle cx={box[2] * W} cy={box[3] * H} r={handle} onPointerDown={startDrag("box-br")} />}
            </g>
          )}
        </svg>
      </div>
        {result && (
        <figure className="scene-result">
          <img src={result} alt="Preview" />
          <figcaption className="muted small">Preview with your product. The product is your real photo, only reshaped to lie in the scene.</figcaption>
        </figure>
      )}
      </div>

      <label className="inline small">
        View angle: from the front
        <input type="range" min={0.18} max={0.5} step={0.01} value={geo.tilt}
          onChange={(e) => { setGeo({ ...geo, tilt: Number(e.target.value) }); setDirty(true); }} />
        from above
      </label>
      <label className="inline small">
        Dress size
        <input type="range" min={0.6} max={1.15} step={0.01} value={geo.scale}
          onChange={(e) => { setGeo({ ...geo, scale: Number(e.target.value) }); setDirty(true); }} />
        {Math.round(geo.scale * 100)}%
      </label>
      <p className="muted small">
        The oval marks what gets cleared away; <em>Dress size</em> sets how big the new product is inside it.
        The top of the red box is where the neckline goes, so keep it below the chin.
      </p>

      <div className="actions">
        <button className="btn btn-primary" onClick={check} disabled={saving}>{saving ? "Working…" : "Save & check"}</button>
        <PhotoButton label={trying ? "Making preview…" : product ? "Try another product" : "Try with a product photo"}
          onPhoto={tryWith} variant="secondary" multiple={false} disabled={trying} />
        {product && <button className="link" onClick={() => tryWith(product)} disabled={trying}>Try again</button>}
      </div>

      {checked && (
        <div className="notice small">
          Arms, hands or jewellery missing in the preview? Pick <strong>Keep brush</strong>, paint over them, then
          <strong> Save &amp; check</strong> again. Bits of the old product still showing? Use <strong>Erase brush</strong>.
        </div>
      )}


      <button className="link danger" onClick={() => window.confirm(`Delete scene "${scene.name}"?`) && onDelete()}>
        Delete this scene
      </button>
    </section>
  );
}
