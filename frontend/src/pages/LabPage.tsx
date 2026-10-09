import { useCallback, useEffect, useState } from "react";
import { lab, type LabJob, type LabStatus } from "../api";
import { PhotoButton } from "../components/PhotoButton";
import { useShop } from "../shop";

const SCENE_LABELS: Record<string, string> = {
  table: "Wooden table",
  marble: "Marble studio",
  festive: "Festive lights",
  nature: "Leaves & daylight",
  silk: "Silk drape",
  custom: "Describe your own",
};

export function LabPage({ toast }: { toast: (m: string) => void }) {
  const { shop } = useShop();
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [looks, setLooks] = useState<string[]>(["main_white", "shadow_grey", "gradient", "tabletop", "closeup", "card"]);
  const [scene, setScene] = useState("table");
  const [custom, setCustom] = useState("");
  const [aiCount, setAiCount] = useState(2);
  const [title, setTitle] = useState("");
  const [bullets, setBullets] = useState("");
  const [job, setJob] = useState<LabJob | null>(null);
  const [recent, setRecent] = useState<LabJob[]>([]);
  const [prefix, setPrefix] = useState(`${shop.sku_prefix || "IMG"}-00001`);

  const loadRecent = useCallback(() => lab.jobs().then(setRecent).catch(() => undefined), []);

  useEffect(() => {
    lab.status().then((s) => {
      setStatus(s);
      if (s.generator.available) setLooks((l) => (l.includes("ai_scene") ? l : [...l, "ai_scene"]));
    }).catch((e) => toast(e.message));
    loadRecent();
  }, [toast, loadRecent]);

  useEffect(() => {
    if (!file) return;
    const u = URL.createObjectURL(file);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  // Poll the running job.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const t = setInterval(async () => {
      try {
        const j = await lab.job(job.id);
        setJob(j);
        if (j.status === "done" || j.status === "failed") loadRecent();
      } catch {
        /* keep polling */
      }
    }, 1000);
    return () => clearInterval(t);
  }, [job, loadRecent]);

  const others = recent.filter((r) => r.id !== job?.id && r.outputs.length);

  async function generate() {
    if (!file) return toast("Choose a product photo first");
    if (!looks.length) return toast("Pick at least one look");
    try {
      setJob(await lab.create(file, { looks, scene, custom_prompt: custom, ai_count: aiCount, title, bullets }));
    } catch (e) {
      toast((e as Error).message);
    }
  }

  const toggle = (k: string) => setLooks((l) => (l.includes(k) ? l.filter((x) => x !== k) : [...l, k]));
  const running = job && (job.status === "queued" || job.status === "running");
  const gen = status?.generator;

  return (
    <section>
      <div className="page-head">
        <h1>Listing photos <span className="chip">beta</span></h1>
      </div>
      <p className="muted">
        Upload one product photo and get a set of marketplace-ready images. Your product always stays the real photo;
        only the background, framing and text are made for you, on this computer.
      </p>

      {status && (
        <div className="engines small">
          <span className={status.cutout.engine === "rembg" ? "ok" : "warn"}>
            ● Cut-out: {status.cutout.engine === "rembg" ? `AI (${status.cutout.model})` : "basic - plain backgrounds only"}
          </span>
          <span className={gen?.available ? "ok" : "warn"}>
            ● AI scenes: {gen?.available ? `${gen.model} on ${gen.device?.toUpperCase()}` : "not installed"}
          </span>
          {(status.cutout.hint || !gen?.available) && (
            <span className="muted">Install extras: <code>pip install -r requirements-imagelab.txt</code></span>
          )}
        </div>
      )}

      <div className="lab-grid">
        <div className="lab-left">
          <div className="lab-photo">
            {preview ? <img src={preview} alt="Your photo" /> : <span className="muted">Your product photo</span>}
          </div>
          <div className="actions">
            <PhotoButton label={file ? "Change photo" : "Choose photo"} onPhoto={setFile} multiple={false} variant={file ? "secondary" : "primary"} />
          </div>
          <p className="muted small">Tip: product on a plain background, good light, filling most of the frame.</p>
        </div>

        <div className="lab-right">
          <h2>Images to make</h2>
          <div className="look-chips">
            {status &&
              Object.entries(status.looks).map(([k, label]) => (
                <button
                  key={k}
                  className={`fchip ${looks.includes(k) ? "on" : ""}`}
                  onClick={() => toggle(k)}
                  disabled={k === "ai_scene" && !gen?.available}
                  title={k === "ai_scene" && !gen?.available ? "Install the AI image extras first" : ""}
                >
                  {label}
                </button>
              ))}
          </div>

          {looks.includes("ai_scene") && (
            <div className="lab-box">
              <strong>AI scene</strong>
              <div className="look-chips">
                {(status?.scenes ?? []).map((s) => (
                  <button key={s} className={`fchip ${scene === s ? "on" : ""}`} onClick={() => setScene(s)}>
                    {SCENE_LABELS[s] ?? s}
                  </button>
                ))}
              </div>
              {scene === "custom" && (
                <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="e.g. decorated wooden shelf with marigold flowers, warm light" />
              )}
              <label className="inline">
                How many
                <select value={aiCount} onChange={(e) => setAiCount(Number(e.target.value))}>
                  {[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}
                </select>
              </label>
              <p className="muted small">The AI paints only the background; your real product is placed on top. On a laptop without a graphics card each scene can take a while.</p>
            </div>
          )}

          {looks.includes("card") && (
            <div className="lab-box">
              <strong>Details card</strong>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title, e.g. Rose Silk Dress" />
              <textarea
                rows={4}
                value={bullets}
                onChange={(e) => setBullets(e.target.value)}
                placeholder={"One point per line, e.g.\nPure cotton, soft lining\nHand embroidered\nIncludes dress + belt"}
              />
            </div>
          )}

          <button className="btn btn-primary btn-big" onClick={generate} disabled={!file || !!running}>
            {running ? "Working…" : "Make images"}
          </button>
        </div>
      </div>

      {job && (
        <div className="lab-results">
          <div className="lab-progress">
            {running && <span className="spinner" />}
            <span>
              {job.status === "done"
                ? `Done in ${job.total_s}s - ${job.outputs.length} images`
                : job.status === "failed"
                  ? job.message
                  : job.message}
            </span>
            {job.status === "done" && job.outputs.length > 0 && (
              <span className="zip">
                <input value={prefix} onChange={(e) => setPrefix(e.target.value)} aria-label="File name prefix (SKU)" />
                <a className="btn btn-primary" href={lab.zipUrl(job.id, prefix)}>Download all (.zip)</a>
              </span>
            )}
          </div>
          {job.notes.map((n) => (
            <div key={n} className="notice warn">{n}</div>
          ))}
          <div className="lab-out">
            {job.outputs.map((o) => (
              <figure key={o.file}>
                <a href={lab.fileUrl(job.id, o.file)} target="_blank" rel="noreferrer">
                  <img src={lab.fileUrl(job.id, o.file)} alt={o.label} loading="lazy" />
                </a>
                <figcaption>
                  <strong>{o.label}</strong>
                  <span className="muted small">{o.seconds}s · {o.kb} KB</span>
                  {o.note && <span className="muted small">{o.note}</span>}
                  <a className="link small" href={lab.fileUrl(job.id, o.file)} download>Download</a>
                </figcaption>
              </figure>
            ))}
            {running && <figure className="placeholder"><span className="spinner big" /></figure>}
          </div>
        </div>
      )}

      {others.length > 0 && (
        <>
          <h2>Recent</h2>
          <div className="lab-recent">
            {others.map((r) => (
              <button key={r.id} className="lab-thumb" onClick={() => setJob(r)}>
                <img src={lab.fileUrl(r.id, r.outputs[0].file)} alt="" loading="lazy" />
                <span className="small muted">{r.outputs.length} images</span>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
