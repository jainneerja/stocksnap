# Architecture

```
 Phone / laptop browser (React + Vite)
        │  HTTP on local Wi-Fi
        ▼
 FastAPI (uvicorn) ──── serves built UI + /images
   │
   ├── routers/items      CRUD, stock adjust, CSV export
   ├── routers/scan       /scan (fast)  /describe (slow, async in UI)
   ├── routers/sales      sales, void, expenses
   ├── routers/reports    summary, CSV exports
   └── routers/system     health, backup
        │
   services/
   ├── barcode.py   zxing-cpp ──────────────── in-process
   ├── matcher.py   OpenCLIP or Lite embedder ─ in-process, numpy cosine search
   ├── vision.py    Ollama HTTP client ──────── localhost:11434 (qwen2.5vl / moondream)
   └── images.py    EXIF-safe load, downscale, traversal-safe paths
        │
   SQLite (WAL) + images/   in ~/.stocksnap
```

## Key decisions

**Scan is split into two calls.** `/api/scan` saves the photo, reads the barcode and runs similarity search, all in well under a second. `/api/describe` runs the vision-language model, which can take 5–30 s on a CPU. The UI shows the form straight away, and when the AI draft arrives it fills only the fields the user hasn't typed in yet. The seller is never left waiting on AI.

**Tag close-ups for size and price.** Handmade goods rarely have barcodes, but they usually have a size label or hang tag. `/api/photos` saves a sharper close-up (1600 px so small print survives), and `/api/describe` sends it to the vision model as a second image, asking it to copy size and price exactly as printed and never guess. Items are matched by name + size: a new size is a separate item with a SKU like `TSH-00012-L`, and saving the same name + size again returns 409 with an "add stock instead" prompt.

**Bulk add uses classic computer vision, not a detection model.** A model like YOLO would need training on jewellery and still miss unusual pieces. Because the seller controls the setup (a plain, contrasting, matte background), OpenCV can do the job instantly on CPU with nothing to download. It estimates the background colour from the photo's border, marks pixels that differ (in Lab colour space, with a threshold set from the background's own noise so low-contrast kraft wrappers still count), cleans up with morphology, and treats each blob as one item. If the mat doesn't fill the frame, it detects the mat and re-runs inside it. Items are numbered in reading order, which is also the order the tags print in.

**Batches → photos → detections → groups.** A *group* is what becomes one inventory item. In one-of-a-kind mode every detection is its own group. In identical mode, crops are grouped by visual similarity, the AI describes one representative per group, and groups whose label text reads the same are then merged (lighting differences can split identical bars). The AI runs as a background task, committing per group so the UI can show progress. Saving is idempotent, so a double-click never adds stock twice.

**A stock ledger, not just a quantity column.** Every change goes through `ledger.move()` and writes a `StockMove` (initial, intake, sale, void, adjust). `Item.quantity` stays as a fast cache. The monthly report sums moves before the month (opening) and within it (added, sold, adjusted). Databases from v0.1 are migrated on start: missing columns are added, and the ledger is backfilled from current stock plus past sales.

**One folder per shop.** `ShopRegistry` keeps each shop in `<data_dir>/shops/<slug>/` (`shop.json`, `stocksnap.db`, `images/`, `logo.png`). The current shop is chosen per request from a cookie (or `?shop=`), so photos, CSV downloads and API calls all follow the shop the user picked, with no extra parameters in the UI. Engines are cached per shop, and background AI jobs are keyed by shop and batch. Separate files were chosen over a `shop_id` column: inventories can't leak into each other, backups are a single folder, and the existing queries didn't change.

**Local-first AI behind small interfaces.** `OllamaVision` and `Embedder` are the only places that touch models. You can swap the model with an environment variable, and tests inject fakes. Ollama was chosen because it installs with one click on Windows, Mac and Linux, handles GPU and CPU automatically, and hosts many open vision models.

**Re-identification over generic detection.** Generic detectors such as YOLO or COCO know "cup" and "person", but they can't tell your lavender candle apart from your cedar candle. Embedding each saved item's photo and comparing new photos against *your own catalogue* is what makes "snap to sell" and "snap to restock" work.

**Money as integer cents, cost snapshotted per sale.** This avoids float drift and keeps past profit accurate when you later change an item's cost.

**Timestamps in UTC, reports by local day.** Sales are stored timezone-aware, and a report for "September" uses the seller's local midnight boundaries.

**One process in production.** FastAPI serves the built React bundle, so a non-technical user runs a single command (and later, a packaged installer).

## Data model

- **Item**: sku (unique, auto `TSH-00001`), name, description, category, tags, color, size, material, barcode (unique), cost_cents, price_cents, quantity, low_stock_threshold, image_path, embedding and embedding_model
- **Sale**: item_id, item_name (snapshot), quantity, unit_price_cents, unit_cost_cents (snapshot), sold_at
- **Expense**: category, description, amount_cents, spent_on

## Testing

`backend/tests` covers inventory rules, oversell prevention, void and restock, report arithmetic, CSV exports, barcode decoding (with generated EAN-13 images), visual matching, AI fallback, messy LLM JSON parsing, path-traversal protection and backup.
