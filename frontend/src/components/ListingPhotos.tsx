import { useEffect, useState } from "react";
import { imageUrl, listing, scenes, type Item, type ListingJob, type Scene } from "../api";

/**
 * Put saved products into the shop's scenes in one go, e.g. right after a bulk
 * add. One set of scenes for everything, or a different choice per product.
 */
export function ListingPhotos({ items, toast }: { items: Item[]; toast: (m: string) => void }) {
  const [all, setAll] = useState<Scene[] | null>(null);
  const [forAll, setForAll] = useState<string[]>([]);
  const [perItem, setPerItem] = useState(false);
  const [choice, setChoice] = useState<Record<number, string[]>>({});
  const [white, setWhite] = useState(true);
  const [job, setJob] = useState<ListingJob | null>(null);
  const withPhoto = items.filter((it) => it.image_path);

  useEffect(() => {
    scenes.list().then((s) => {
      setAll(s);
      if (s.length) setForAll([s[0].id]);
    }).catch((e) => toast(e.message));
  }, [toast]);

  useEffect(() => {
    if (!job || job.status === "done") return;
    const t = setInterval(() => listing.get(job.id).then(setJob).catch(() => undefined), 1000);
    return () => clearInterval(t);
  }, [job]);

  const scenesFor = (it: Item) => (perItem ? choice[it.id] ?? forAll : forAll);
  const count = withPhoto.reduce((n, it) => n + scenesFor(it).length + (white ? 1 : 0), 0);

  async function start() {
    try {
      setJob(await listing.create(withPhoto.map((it) => ({ item_id: it.id, scene_ids: scenesFor(it) })), white));
    } catch (e) {
      toast((e as Error).message);
    }
  }

  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  if (all === null) return null;
  return (
    <div className="listing-photos">
      <h2>Listing photos</h2>
      {!withPhoto.length ? (
        <p className="muted">These items have no photos.</p>
      ) : !all.length ? (
        <p className="muted">
          Put these {withPhoto.length} products into your own scene photos. First add a scene in{" "}
          <a href="#photos">Photos → Your scenes</a> (one nice photo of your setup, or any base image).
        </p>
      ) : (
        <>
          <p className="muted small">
            Your real product photos are placed into your scenes, about a second each, on this computer.
          </p>
          <div className="scene-picks">
            {all.map((s) => (
              <button key={s.id} className={`scene-pick ${forAll.includes(s.id) ? "on" : ""}`} onClick={() => setForAll(toggle(forAll, s.id))}>
                <img src={scenes.fileUrl(s.id, "thumb.jpg")} alt="" />
                <span className="small">{s.name}</span>
              </button>
            ))}
          </div>
          <label className="check">
            <input type="checkbox" checked={white} onChange={(e) => setWhite(e.target.checked)} /> Also a plain white main image
          </label>
          {all.length > 1 && (
            <label className="check">
              <input type="checkbox" checked={perItem} onChange={(e) => setPerItem(e.target.checked)} /> Choose scenes per product
            </label>
          )}
          {perItem && (
            <ul className="per-item">
              {withPhoto.map((it) => (
                <li key={it.id}>
                  <img src={imageUrl(it.image_path!)} alt="" />
                  <span className="small">{it.sku}</span>
                  <span className="chips">
                    {all.map((s) => (
                      <button key={s.id} className={`fchip ${scenesFor(it).includes(s.id) ? "on" : ""}`}
                        onClick={() => setChoice({ ...choice, [it.id]: toggle(scenesFor(it), s.id) })}>
                        {s.name}
                      </button>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="actions">
            <button className="btn btn-primary" disabled={!count || (job !== null && job.status !== "done")} onClick={start}>
              Make {count} photos
            </button>
          </div>
        </>
      )}

      {job && (
        <>
          {job.status !== "done" ? (
            <div className="progress">
              <div className="progress-bar" style={{ width: `${(100 * job.done) / Math.max(1, job.total)}%` }} />
              <span><span className="spinner" /> Product {Math.min(job.done + 1, job.total)} of {job.total}…</span>
            </div>
          ) : (
            <div className="notice">
              Done: {job.outputs.length} photos in {job.total_s} s.{" "}
              <a className="btn btn-secondary" href={listing.zipUrl(job.id)}>Download all (.zip, one folder per SKU)</a>
            </div>
          )}
          {job.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
          <div className="lab-out">
            {job.outputs.map((o) => (
              <figure key={o.file}>
                <img src={listing.fileUrl(job.id, o.file)} alt={o.label} loading="lazy" />
                <figcaption>
                  <strong>{o.sku}</strong> <span className="muted small">{o.label}</span>
                  <a className="small" href={listing.fileUrl(job.id, o.file)} download={`${o.sku}-${o.file}`}>Download</a>
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
