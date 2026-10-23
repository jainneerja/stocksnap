# StockSnap

**Offline, open-source inventory and bookkeeping for makers and micro-retailers, with local AI.**

Snap a photo of an item, plus an optional close-up of its size or price tag. StockSnap reads any barcode, recognises items you already stock, and uses a local vision-language model to draft the name, description and tags. It also reads the **size and price straight off the tag**, so items with no barcode still get listed without typing. Selling takes one tap, stock updates on its own, and the Money tab shows what you earned this month. It all runs on your laptop, so no subscription is needed and none of your data leaves your device.

![StockSnap screens](docs/screenshots.png)

![Reading size and price from a tag](docs/screenshots-sizes.png)

| Add | Bulk | Sell | Inventory | Money |
|---|---|---|---|---|
| Photo (+ tag close-up) → barcode → "do I already have this?" → AI-drafted listing with size & price | Hundreds of items from a few tray photos: counted, numbered, described, barcode tags printed | Tap a tile or snap a photo to sell; undo mistakes | Search, low-stock flags, ± stepper, CSV export | Profit, expenses, **stock by month** (start, added, sold, end); CSV + print to PDF; full backup |

## Your shops

The first time StockSnap opens, it asks for your **shop or brand name**, what you mainly sell (clothing, jewellery, soaps & bath, candles, or something else), a **SKU prefix** (for example *Sora in Bloom* gives `SIB-00012`), a low-stock level and an optional **logo**. The name and logo appear in the header, on printed price tags and on reports.

You can run **several shops** on one laptop, for example a clothing line and a jewellery line, and switch between them from the header. Each shop is its own folder (`~/.stocksnap/shops/<shop>/`) with its own database, photos and settings, so inventories never mix and a shop can be backed up by copying one folder. Shops keep your data organised; they aren't password-protected.

Items can also carry a **brand / maker** (useful for resellers), which you can filter by and which the AI reads off labels.

## Bulk add: 500 pieces from a few photos

Wholesale lots arrive in bulk: a bag of 500 machine-made earrings, or a carton of soaps. Photographing them one at a time doesn't work, so StockSnap can take a whole tray at once.

1. **Pick the product type.** Clothing, jewellery, soaps & bath, candles, or something else. Each comes with a **photo guide** (which background to use, how far apart to lay things out, how many per photo).
2. **Answer a few questions once per batch.** These cover what the camera can't see: metal, stones, nickel-free, wax type, cost and price. The answers apply to every item in the batch, so the AI never has to guess a metal.
3. **Photograph the trays.** StockSnap finds every item, draws a **numbered box** on each and counts them. Tap a box to drop anything that isn't an item.
4. **Local AI describes them in the background.** It works out the type, colour, finish and style, and on packaged goods **reads the label** (name, scent, weight).
5. **Review in one list,** set prices in bulk ("all earrings $22"), then **save**. Every item gets its own SKU and a **sheet of barcode tags** prints in tray order: tag #1 goes on piece #1.

Two counting modes:

- **One of a kind** (jewellery): every piece found becomes its own item and ID.
- **Identical goods** (soaps, candles): look-alikes are grouped and counted, with one AI call per product rather than per bar. Groups whose labels read the same are merged, and a product you already stock is **restocked** instead of duplicated. For a full carton, type the count.

![Bulk add](docs/screenshots-bulk.png)

**Photo setup:** use a **matte black** background (velvet, felt, foam board) for gold, silver, pearls and bright items, and **plain white card** for dark items. Shoot in daylight with no flash, phone straight overhead, with a finger-width gap between items. Earring pairs should touch, so each pair counts as one.

## Fast descriptions with templates

On a laptop CPU, most of the AI's time goes into *writing words*, so StockSnap lets each shop pick how item names and descriptions are written (Shop settings → Item names and descriptions):

| Mode | How | Speed |
|---|---|---|
| **Instant** | No AI. Colours are read from the photo's pixels, the type comes from what you told it ("What is it?", batch answers), and your template writes the text | under a second |
| **Fast AI** (default) | The model answers a few short facts (type, colours, pattern, printed text) and your template writes the text | several times quicker than free writing |
| **Detailed AI** | The model writes everything itself | slowest |

Templates use blanks like `{colour} {type}[ with {pattern}]. [Size {size}. ]Made with care by {shop}.` Anything in square brackets disappears when its blank is unknown. Every listing reads in the shop's own style, and if the AI isn't running, Fast falls back to Instant.

## Your scenes: real products in your own setting

Upload one nice photo of your setup (your own idol and mandir, a styled table, or any base image made once with an AI tool) and turn it into a **scene**:

**Quickest:** click **Set up automatically**, type what should be replaced (`dress`) and what should stay on top (`hand, arm, necklace, anything held in a hand`), and press **Find them for me**. The local vision model (Qwen2.5-VL via Ollama) finds each one; the app places the oval and box and traces exact outlines inside what it found. Takes about 1-2 minutes on a laptop CPU, once per scene. Then check and fix anything with the tools below.

By hand:

1. Drag the oval over where the product lies, and the box over the chest if the product has a top piece (bodice).
2. **Save & check**: the app finds the old product by its colours and removes it; anything else (hands, jewellery, hair) stays on top. Blue = replaced, green = kept.
3. **Outline** parts it removed by clicking points around them (e.g. gold arms next to gold sequins) - the most exact - or paint them with the **Keep** brush; **Erase** leftovers. Set the new product's size with **Dress size**.
4. Try it with a product photo.

After a **bulk add**, *Listing photos* puts every saved product into your scenes (same scenes for all, or chosen per product), plus an optional white main image, and downloads one ZIP with a folder per SKU (`SKU.MAIN.jpg`, `SKU.PT01.jpg`…). The Photos tab offers the same for single photos.

It's image processing, not generative AI: about half a second per image on any laptop, and the product is always the seller's real photo, so colours and embroidery are exact.

## Product catalogue from a folder of photos

Put one photo per product in a folder (the file name can be the product's name, e.g.
`red-leaves-dress.jpg`; camera names like `IMG_2041.jpg` are fine too). In the
**Catalogue** tab, pick the folder and say what the products are ("Laddu Gopal dresses").
StockSnap writes a name and short description for each photo with the shop's own
description settings (instant templates, fast AI or detailed AI; with the AI off it
uses templates), you add prices (or one price for all), codes and a contact line, and
download a **PDF catalogue**: a cover page with your logo, then 4 big or 9 small product
cards per page. Optionally the products are cut out onto a clean white background.
Your photos are not moved or changed; the app keeps its own copy.

## Tell the AI what you sell

A small vision model only sees shapes and colours, so it can call a round embroidered outfit a "hat". You can tell it what your items really are, in your own words, in three places:

- **Shop settings → Describe what you sell**: read before every photo in that shop.
- **Bulk → What are these?**: applies to one batch. If the names come back wrong anyway, use **Redo names** on the review screen. Prices and counts are kept.
- **Add → What is it?**: for a single item, with **Ask AI again** on the form.

The note is given to the model as the seller's word, which it must not contradict. It is never saved on your items.

## Listing photos (beta)

The **Photos** tab turns one product photo into a set of marketplace images: a main image on pure white (2000×2000, product filling about 85% of the frame, as Amazon asks), a soft-shadow shot, a colour backdrop, a tabletop shot, a close-up of the most detailed area, and a details card with your title and bullet points. Download them one by one or as a ZIP named `SKU.MAIN.jpg`, `SKU.PT01.jpg`, and so on.

**The product is always the real photo.** The AI cuts it out and paints only the background around it. It never redraws the product, so colours, embroidery and print stay true. Back views, side views and the package contents still need their own photos.

| Step | Model | Licence | Speed on a laptop CPU |
|---|---|---|---|
| Cut the product out | **rembg** with `isnet-general-use` (OpenCV GrabCut if rembg isn't installed) | MIT / Apache-2.0 | ~2 s per photo |
| White, shadow, backdrop, tabletop, close-up, card | Pillow + OpenCV | open source | under 1 s each |
| AI scene backgrounds (optional) | **SD-Turbo** via diffusers | Stability AI Community Licence (check before commercial use) | ~10–60 s per scene on CPU, 1–2 s on a GPU |

Install the extras (in Git Bash on Windows, with the venv active):

```bash
cd backend
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu   # skip if you have an NVIDIA GPU build
python -m pip install -r requirements-imagelab.txt
```

The models download the first time you use them (about 180 MB for the cut-out model and about 2 GB for SD-Turbo), and after that everything runs offline. Without the extras, the Photos tab still works, using the basic cut-out with no AI scenes.

## Why

Home-based sellers, craft makers and small boutique owners usually juggle spreadsheets, notebooks and a partial POS. The tools built for them tend to be subscription-based, cloud-only, or built for enterprise. StockSnap is aimed at the **handmade seller at a weekend market**: fast enough to use at the booth, simple enough to use without accounting knowledge, and private because everything stays on your machine.

See [docs/PROBLEM_AND_REQUIREMENTS.md](docs/PROBLEM_AND_REQUIREMENTS.md) for the full problem statement and scope.

## Open-source AI stack

| Job | Model / library | Licence | Runs |
|---|---|---|---|
| Draft name, description, tags from a photo; read size & price from a tag | **Qwen2.5-VL 3B** via [Ollama](https://ollama.com) (or `moondream` for low-end laptops) | Apache-2.0 | Local, CPU or GPU |
| "Which of my items is this?" | **OpenCLIP ViT-B/32** (optional) or the built-in lite colour/shape matcher | MIT | Local |
| Barcodes (UPC, EAN, Code128, QR, …) and printed SKU tags | **zxing-cpp** | Apache-2.0 | Local |
| Finding and counting items on a tray photo | **OpenCV** | Apache-2.0 | Local, instant on CPU |
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
source .venv/Scripts/activate     # Windows Git Bash  (PowerShell: .venv\Scripts\activate;  Mac/Linux: source .venv/bin/activate)
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
| `STOCKSNAP_DATA_DIR` | `~/.stocksnap` | Shops (each with its own database and photos) |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama server |
| `STOCKSNAP_VISION_MODEL` | `qwen2.5vl:3b` | Any Ollama vision model |
| `STOCKSNAP_VISION_TIMEOUT` | `300` | Seconds to wait for the model |
| `STOCKSNAP_MATCHER` | `auto` | `auto` / `clip` / `lite` / `off` |
| `STOCKSNAP_MATCH_THRESHOLD` | `0.80` | Minimum similarity to suggest a match |
| `STOCKSNAP_CUTOUT_MODEL` | `isnet-general-use` | rembg model for cut-outs (e.g. `u2net`, `birefnet-general-lite`) |
| `STOCKSNAP_IMAGEGEN_MODEL` | `stabilityai/sd-turbo` | Any diffusers text-to-image model for AI scenes |

## Project layout

```
backend/
  app/
    main.py            FastAPI app factory; also serves the built UI
    models.py          SQLModel tables (Item, Sale, Expense), money in cents
    routers/           items, scan, sales & expenses, reports, system
    services/          barcode, vision (Ollama), matcher (CLIP / lite), images, imagelab (listing photos)
  tests/               pytest suite (AI faked for speed)
frontend/
  src/pages/           Add stock, Bulk, Sell, Inventory, Photos, Money
  src/components/      PhotoButton, ItemForm
docs/                  problem & requirements, architecture
```

## Roadmap

- [x] Printable SKU barcode labels
- [x] Bulk add from tray photos (jewellery, soaps, candles, other)
- [x] Stock by month with a full stock ledger
- [ ] Import supplier invoices / packing lists to fill in metal, cost and quantities
- [ ] SAM 2 segmentation as an option for busy backgrounds
- [x] Sizes: read from tag, "different size" of an existing product, duplicate-size guard
- [ ] Full variant matrix (size × colour) under one parent product
- [ ] CSV import from Etsy / Square / Shopify exports
- [ ] Optional sync (local-first, e.g. CRDT or self-hosted)
- [x] Listing photos from one product photo (cut-out, white main image, scenes, details card)
- [ ] Size chart and package-contents images
- [ ] Packaged desktop installer (Tauri or PyInstaller)
- [ ] PWA install on phone

## Licence

MIT. See [LICENSE](LICENSE).
