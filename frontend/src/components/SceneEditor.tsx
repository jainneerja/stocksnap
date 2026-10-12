import { useEffect, useRef, useState } from "react";
import { scenes, type Scene, type Stroke } from "../api";
import { PhotoButton } from "./PhotoButton";

type Tool = "shape" | "outline" | "keep" | "erase";
type Pt = [number, number];
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
  empty_base: boolean;
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
    cx: scene.cx, top: scene.top, bottom: scene.bottom, rx: scene.rx, tilt: scene.tilt, scale: scene.scale ?? 1, empty_base: !!scene.empty_base, top_box: scene.top_box,
  });
  const [keep, setKeep] = useState<Stroke[]>(scene.keep);
  const [erase, setErase] = useState<Stroke[]>(scene.remove);
  const [outlines, setOutlines] = useState<Pt[][]>(scene.keep_outlines ?? []);
  const [drawingOutline, setDrawingOutline] = useState<Pt[]>([]);
  const [history, setHistory] = useState<("keep" | "erase" | "outline")[]>([]);

  function finishOutline(pts: Pt[] = drawingOutline) {
    if (pts.length >= 3) {
      setOutlines((o) => [...o, pts]);
      setHistory((h) => [...h, "outline"]);
      setDirty(true);
    }
    setDrawingOutline([]);
  }

  function undo() {
    if (drawingOutline.length) return setDrawingOutline((d) => d.slice(0, -1));
    const last = history[history.length - 1];
    if (!last) return;
    if (last === "outline") setOutlines((o) => o.slice(0, -1));
    else if (last === "erase") setErase((r) => r.slice(0, -1));
    else setKeep((k) => k.slice(0, -1));
    setHistory((h) => h.slice(0, -1));
    setDirty(true);
  }
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
    if (tool === "outline") {
      // click points round the arm / hand; click the first point again (or Finish) to close
      const p = pos(e);
      const first = drawingOutline[0];
      if (first && drawingOutline.length >= 3 && Math.hypot(p[0] - first[0], (p[1] - first[1]) * aspect) < 0.02) {
        finishOutline();
      } else setDrawingOutline((d) => [...d, p]);
      return;
    }
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
      setHistory((h) => [...h, tool === "keep" ? "keep" : "erase"]);
      setDirty(true);
    }
  }

  async function save(): Promise<Scene | null> {
    // an outline still being drawn: close it (3+ points) rather than silently dropping it
    let allOutlines = outlines;
    if (drawingOutline.length >= 3) {
      allOutlines = [...outlines, drawingOutline];
      setOutlines(allOutlines);
      setHistory((h) => [...h, "outline"]);
      setDrawingOutline([]);
    } else if (drawingOutline.length > 0) {
      toast("An outline needs points all round the part - click round its edge, then click the first dot to close.");
    }
    setSaving(true);
    try {
      const s = await scenes.update(scene.id, { ...geo, top_box: geo.top_box ?? [], keep, remove: erase, keep_outlines: allOutlines, name });
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
  const fresh = !scene.keep_outlines?.length && !scene.keep.length;
  const [autoProduct, setAutoProduct] = useState("dress");
  const [autoKeep, setAutoKeep] = useState("hand, arm, necklace, anything held in a hand");
  const [autoTop, setAutoTop] = useState(true);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoNotes, setAutoNotes] = useState<string[]>([]);

  async function autoSetup() {
    setAutoBusy(true);
    setAutoNotes([]);
    try {
      const r = await scenes.auto(scene.id, { product: autoProduct, keep: autoKeep, top_piece: autoTop });
      const s = r.scene;
      setGeo({ cx: s.cx, top: s.top, bottom: s.bottom, rx: s.rx, tilt: s.tilt, scale: s.scale ?? 1, empty_base: !!s.empty_base, top_box: s.top_box });
      setOutlines(s.keep_outlines ?? []);
      setKeep(s.keep);
      setErase(s.remove);
      setHistory([]);
      setDrawingOutline([]);
      setDirty(false);
      setVersion((v) => v + 1);
      setView("layers");
      setChecked(true);
      setAutoNotes([`Done in ${r.seconds} s.`, ...r.notes]);
      onSaved(s);
      if (product) await render(product);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setAutoBusy(false);
    }
  }

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

      <details className="auto-setup" open={fresh}>
        <summary><strong>Set up automatically</strong> <span className="muted small">- tell the local AI what's what</span></summary>
        <label>
          What should be replaced?
          <input value={autoProduct} maxLength={60} onChange={(e) => setAutoProduct(e.target.value)} placeholder="dress" />
        </label>
        <label>
          What should stay on top of it? <span className="muted small">(comma separated)</span>
          <input value={autoKeep} maxLength={300} onChange={(e) => setAutoKeep(e.target.value)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={autoTop} onChange={(e) => setAutoTop(e.target.checked)} /> It has a top part on the chest (bodice)
        </label>
        <button className="btn btn-primary" onClick={autoSetup} disabled={autoBusy || !autoProduct.trim()}>
          {autoBusy ? "Local AI is looking… (1-2 min on a laptop)" : "Find them for me"}
        </button>
        {autoNotes.length > 0 && <ul className="small">{autoNotes.map((n) => <li key={n}>{n}</li>)}</ul>}
        <p className="muted small">Then check the result and fix anything with the tools below.</p>
      </details>

      <ol className="steps small muted">
        <li><strong>Shape:</strong> drag the oval over where the product lies. Turn on the top-piece box for dresses with a bodice.</li>
        <li><strong>Check</strong> what the app found: <span className="sw blue" /> replaced, <span className="sw green" /> kept on top.</li>
        <li><strong>Outline</strong> arms, hands or jewellery it removed (click points around each, click the first point to close) - the most exact. Or paint them with the <strong>Keep brush</strong>; <strong>Erase</strong> leftovers of the old product.</li>
        <li><strong>Try</strong> it with a real product photo.</li>
      </ol>

      <div className="scene-tools">
        <div className="seg" role="group" aria-label="Tool">
          {(["shape", "outline", "keep", "erase"] as Tool[]).map((t) => (
            <button key={t} className={tool === t ? "on" : ""} onClick={() => setTool(t)}>
              {t === "shape" ? "Shape" : t === "outline" ? "Outline" : t === "keep" ? "Keep brush" : "Erase brush"}
            </button>
          ))}
        </div>
        {tool === "outline" && (
          <>
            <button className="btn btn-secondary small" disabled={drawingOutline.length < 3} onClick={() => finishOutline()}>Finish outline</button>
            <button className="link small" disabled={!drawingOutline.length} onClick={() => setDrawingOutline([])}>Cancel</button>
          </>
        )}
        {(tool === "keep" || tool === "erase") && (
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
                    ? [g.cx - g.rx * 0.3, g.top + (g.bottom - g.top) * 0.12, g.cx + g.rx * 0.3, g.top + (g.bottom - g.top) * 0.42]
                    : null,
                }));
              }}
            />
            Top piece (bodice)
          </label>
        )}
        <button className="link small" disabled={!history.length && !drawingOutline.length} onClick={undo}>
          Undo
        </button>
        <div className="seg" role="group" aria-label="View">
          <button className={view === "scene" ? "on" : ""} onClick={() => setView("scene")}>Photo</button>
          <button className={view === "layers" ? "on" : ""} onClick={() => setView("layers")} disabled={dirty}>Layers</button>
        </div>
      </div>

      {tool === "outline" && (
        <p className="tool-hint small">
          {drawingOutline.length === 0
            ? "Click points all round the edge of an arm, hand or jewellery - like tracing it."
            : drawingOutline.length < 3
              ? "Keep going round the edge…"
              : "Keep going round, then click the first (big) dot or Finish outline to close it."}
        </p>
      )}
      {tool === "shape" && geo.top_box && (
        <p className="tool-hint small">Keep the top of the red box below the chin - that's where the neckline goes.</p>
      )}
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
          {outlines.map((o, i) => (
            <polygon key={`o${i}`} points={o.map(([x, y]) => `${x * W},${y * H}`).join(" ")} className="outline done" />
          ))}
          {drawingOutline.length > 0 && (
            <g className="outline drawing">
              <polyline points={drawingOutline.map(([x, y]) => `${x * W},${y * H}`).join(" ")} />
              {drawingOutline.map(([x, y], i) => <circle key={i} cx={x * W} cy={y * H} r={i === 0 ? 0.012 * W : 0.006 * W} />)}
            </g>
          )}
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

      <label className="check small">
        <input type="checkbox" checked={geo.empty_base}
          onChange={(e) => { setGeo({ ...geo, empty_base: e.target.checked }); setDirty(true); }} />
        Nothing to remove - this photo has no old product on it (e.g. the idol or model without clothes).
        The new product goes over everything except what you mark to keep (hands, jewellery).
      </label>
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
          Arms, hands or jewellery missing in the preview? Use <strong>Outline</strong> (click round them) or the <strong>Keep brush</strong>, then
          <strong> Save &amp; check</strong> again. Bits of the old product still showing? Use <strong>Erase brush</strong>.
        </div>
      )}


      <button className="link danger" onClick={() => window.confirm(`Delete scene "${scene.name}"?`) && onDelete()}>
        Delete this scene
      </button>
    </section>
  );
}
