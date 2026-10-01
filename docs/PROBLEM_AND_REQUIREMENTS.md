# Problem & Requirements

## Problem statement

Home-based sellers, craft makers, market vendors and boutique owners have trouble tracking inventory and knowing whether they're making money. The tools available to them each fall short in one of these ways:

- **Cost**: POS and inventory apps charge monthly subscriptions that eat into thin margins.
- **Complexity**: enterprise inventory and ERP tools assume staff, training and accounting knowledge.
- **Cloud dependence**: most tools need internet access (unreliable at markets) and store business data on someone else's servers.
- **Fragmentation**: stock lives in one app, sales in another, expenses in a spreadsheet.
- **Manual entry**: every product has to be typed in by hand. Handmade goods have no barcode to scan, so nothing can be looked up.

So sellers end up with inaccurate stock counts, missed sales, messy books and a stressful tax season.

**The gap:** no free, open-source tool lets a seller photograph an item, have it catalogued with AI, sell it with one tap and see a monthly profit figure, all running privately on a laptop they already own.

Open-source inventory tools (InvenTree, ERPNext) and bookkeeping tools (GnuCash, Akaunting) do exist. They're powerful, but they're built for warehouses and accountants. StockSnap's difference is the combination of **photo-first capture with local AI**, **offline operation** and **simplicity aimed at micro-sellers**.

## Customer feedback that shaped v0.3

Sellers in a local makers' community said they already try AI for photos and categories, but bulk lots break it. Machine-made jewellery arrives **500 pieces at a time, almost every design different**. That led to bulk add with tray photos, per-batch questions for what AI can't verify (metal), and the same flow generalised to soaps and other packaged goods, where the AI reads the label.

## Primary user

A solo maker who sells tees, candles, jewellery and similar goods at markets and online, has 20 to 1,000 SKUs, and is not an accountant.

## MVP scope (v0.1)

### Functional

| # | Requirement | Status |
|---|---|---|
| F1 | Capture a photo from a phone camera or laptop | ✅ |
| F2 | Read barcodes offline (UPC/EAN/Code128/QR, …) and match them to an existing item's barcode or SKU | ✅ |
| F3 | Visual "which of my items is this?" match against your own catalogue | ✅ CLIP or lite |
| F4 | Local vision-language model drafts name, category, description, colour, material and tags | ✅ Ollama |
| F4a | Optional close-up of a label or hang tag; the model reads the **size and price** exactly as printed | ✅ |
| F4b | Same product in a new size: copy details from the existing item and only change size and stock. Block duplicate name + size, and offer to add stock instead | ✅ |
| F4c | **Bulk add**: find and count every item on a tray photo, number them and give each a unique SKU | ✅ |
| F4d | Per-batch questions for facts the camera can't see (metal, stones, wax, cost, price), applied to every item | ✅ |
| F4e | Identical goods grouped and counted, label text read by AI, existing products restocked rather than duplicated | ✅ |
| F4f | Printable barcode tags in tray order | ✅ |
| F5 | Create and edit items: SKU (auto-generated), price, cost, quantity, size, colour, photo | ✅ |
| F6 | Adjust stock (restock, breakage) and flag low stock | ✅ |
| F7 | Log a sale in one tap, reduce stock, prevent overselling, undo | ✅ |
| F8 | Log expenses by category | ✅ |
| F9 | Monthly report: revenue, cost of goods sold, gross profit, expenses, net profit, best sellers, stock value | ✅ |
| F9a | **Stock by month**: opening, added, sold, adjusted and closing units per item, plus value at cost; every stock change is recorded in a ledger | ✅ |
| F10 | Export CSV (inventory, sales, expenses, summary), print to PDF, full backup zip | ✅ |

### Non-functional

| Area | Target | Approach |
|---|---|---|
| Offline | Works with no internet after setup | All models local; SQLite |
| Privacy | No data leaves the device | No external API calls |
| Speed | Barcode + match < 1 s; inventory ops < 100 ms | AI description runs **asynchronously**. On CPU it takes roughly 5–30 s, so the user keeps typing while it works |
| Low-end hardware | Runs on an 8 GB RAM laptop | `moondream` model option; CLIP optional |
| Reliability | Never blocks on AI | Every AI step has a manual fallback |
| Correctness | No rounding errors; accurate COGS | Integer cents; cost snapshotted on each sale |
| Usability | Non-technical users; phone-friendly | Four tabs, large touch targets, bottom navigation |
| Scale | 10,000 items | Indexed SQLite; vector search in numpy |

### Out of scope (deliberately)

- **Tax calculation.** Rules vary by jurisdiction and mistakes carry liability. StockSnap exports clean CSVs for an accountant or tax software instead.
- **Online barcode lookup.** It would need internet access, and handmade goods rarely have UPCs anyway.
- Multi-user accounts, payments processing and POS hardware.

## Success criteria

- Scan and save a new item in **under 30 s** with AI, or **under 10 s** for a known or barcoded item
- Log a sale in **under 5 s**
- Monthly profit is visible in **one tap**, and nothing on the screen assumes accounting knowledge
- Works with Wi-Fi off
- Validated with real use: the author's own handmade-tee brand, plus feedback from local market vendors
