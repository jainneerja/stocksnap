# StockSnap

**Offline, open-source inventory and bookkeeping for makers and micro-retailers, with local AI.**

Snap a photo of an item. StockSnap reads any barcode, recognises items you already stock, and uses a local vision-language model to draft the name, description and tags. Selling takes one tap, stock updates on its own, and the Money tab shows what you earned this month. It all runs on your laptop, so no subscription is needed and none of your data leaves your device.

![StockSnap screens](docs/screenshots.png)

| Add stock | Sell | Inventory | Money |
|---|---|---|---|
| Photo → barcode → "do I already have this?" → AI-drafted listing | Tap a tile or snap a photo to sell; undo mistakes | Search, low-stock flags, ± stepper, CSV export | Sales, cost of goods, expenses, profit; CSV + print to PDF; full backup |

## Why

Home-based sellers, craft makers and small boutique owners usually juggle spreadsheets, notebooks and a partial POS. The tools built for them tend to be subscription-based, cloud-only, or built for enterprise. StockSnap is aimed at the **handmade seller at a weekend market**: fast enough to use at the booth, simple enough to use without accounting knowledge, and private because everything stays on your machine.

See [docs/PROBLEM_AND_REQUIREMENTS.md](docs/PROBLEM_AND_REQUIREMENTS.md) for the full problem statement and scope.

## Open-source AI stack

| Job | Model / library | Licence | Runs |
|---|---|---|---|
| Draft name, description, tags from a photo | **Qwen2.5-VL 3B** via [Ollama](https://ollama.com) (or `moondream` for low-end laptops) | Apache-2.0 | Local, CPU or GPU |
| "Which of my items is this?" | **OpenCLIP ViT-B/32** (optional) or the built-in lite colour/shape matcher | MIT | Local |
| Barcodes (UPC, EAN, Code128, QR, …) | **zxing-cpp** | Apache-2.0 | Local |
| Storage | SQLite | Public domain | Local file |

Every AI step is **optional and fails gracefully**. If Ollama isn't running, you type the details yourself and everything else still works.

## Quick start

Prerequisites: Python 3.10+ and Node 20+.

```bash
# 1. Local AI (one-time, ~3 GB download)
#    Install Ollama from https://ollama.com, then:
ollama pull qwen2.5vl:3b          # or: ollama pull moondream  (smaller, faster)

# 2. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   |   source .venv/bin/activate  (Mac/Linux)
pip install -r requirements.txt

# 3. Frontend (build once)
cd ../frontend
npm install
npm run build

# 4. Run - one process serves the API and the app
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**. To use your **phone's camera**, connect the phone to the same Wi-Fi and open `http://<your-laptop-ip>:8000`.

### Optional: better visual matching (CLIP)

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-ai.txt
```

The weights download once (~350 MB), and after that matching runs offline. Without CLIP, StockSnap falls back to a lightweight matcher. That matcher works best when photos are taken in similar light and against a similar background.

### Development

```bash
cd backend && uvicorn app.main:app --reload          # API on :8000
cd frontend && npm run dev                           # UI on :5173 (proxies /api)
cd backend && pip install -r requirements-dev.txt && pytest
```

API docs are auto-generated at http://localhost:8000/docs.

## Configuration

All settings are environment variables with sensible defaults:

| Variable | Default | Purpose |
|---|---|---|
| `STOCKSNAP_DATA_DIR` | `~/.stocksnap` | Database and photos |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama server |
| `STOCKSNAP_VISION_MODEL` | `qwen2.5vl:3b` | Any Ollama vision model |
| `STOCKSNAP_VISION_TIMEOUT` | `120` | Seconds to wait for the model |
| `STOCKSNAP_MATCHER` | `auto` | `auto` / `clip` / `lite` / `off` |
| `STOCKSNAP_MATCH_THRESHOLD` | `0.80` | Minimum similarity to suggest a match |

## Project layout

```
backend/
  app/
    main.py            FastAPI app factory; also serves the built UI
    models.py          SQLModel tables (Item, Sale, Expense), money in cents
    routers/           items, scan, sales & expenses, reports, system
    services/          barcode, vision (Ollama), matcher (CLIP / lite), images
  tests/               pytest suite (AI faked for speed)
frontend/
  src/pages/           Add stock, Sell, Inventory, Money
  src/components/      PhotoButton, ItemForm
docs/                  problem & requirements, architecture
```

## Roadmap

- [ ] Printable SKU barcode labels
- [ ] Item variants (size/colour matrix) under one parent product
- [ ] CSV import from Etsy / Square / Shopify exports
- [ ] Optional sync (local-first, e.g. CRDT or self-hosted)
- [ ] Packaged desktop installer (Tauri or PyInstaller)
- [ ] PWA install on phone

## Licence

MIT. See [LICENSE](LICENSE).
