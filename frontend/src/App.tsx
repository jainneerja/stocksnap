import { useCallback, useEffect, useRef, useState } from "react";
import { api, bulk, logoUrl, shops, type Health, type Preset, type Shop } from "./api";
import { BulkPage } from "./pages/BulkPage";
import { InventoryPage } from "./pages/InventoryPage";
import { LabPage } from "./pages/LabPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ScanPage } from "./pages/ScanPage";
import { SellPage } from "./pages/SellPage";
import { ShopSetupPage } from "./pages/ShopSetupPage";
import { ShopContext } from "./shop";

const TABS = [
  { id: "scan", label: "Add" },
  { id: "bulk", label: "Bulk" },
  { id: "sell", label: "Sell" },
  { id: "inventory", label: "Inventory" },
  { id: "photos", label: "Photos" },
  { id: "reports", label: "Money" },
] as const;
type Tab = (typeof TABS)[number]["id"] | "settings" | "new-shop";
const ALL_TABS: Tab[] = [...TABS.map((t) => t.id), "settings", "new-shop"];

export function App() {
  const [tab, setTab] = useState<Tab>(() => {
    const h = location.hash.slice(1) as Tab;
    return ALL_TABS.includes(h) && h !== "new-shop" ? h : "scan";
  });
  const [health, setHealth] = useState<Health | null>(null);
  const [msg, setMsg] = useState("");
  const [shopList, setShopList] = useState<Shop[] | null>(null);
  const [current, setCurrent] = useState<Shop | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [logoVersion, setLogoVersion] = useState(0);
  const [loadError, setLoadError] = useState("");

  const timer = useRef<number>(undefined);
  const toast = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(""), 3500);
  }, []);

  const loadShops = useCallback(async () => {
    try {
      const r = await shops.list();
      setShopList(r.shops);
      setCurrent(r.shops.find((s) => s.slug === r.current) ?? null);
      setLoadError("");
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    bulk.presets().then(setPresets).catch(() => undefined);
    loadShops();
  }, [loadShops]);

  // Follow the address bar too (links like /#reports, browser back/forward).
  useEffect(() => {
    const onHash = () => {
      const h = location.hash.slice(1) as Tab;
      if (ALL_TABS.includes(h)) setTab(h);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    history.replaceState(null, "", `#${tab}`);
  }, [tab]);

  useEffect(() => {
    document.title = current ? `${current.name} · StockSnap` : "StockSnap";
  }, [current]);

  async function switchTo(slug: string) {
    setMenuOpen(false);
    if (slug === current?.slug) return;
    const s = await shops.select(slug);
    setCurrent(s);
    toast(`Switched to ${s.name}`);
  }

  function shopSaved(s: Shop, created: boolean) {
    setCurrent(s);
    setLogoVersion((v) => v + 1);
    loadShops();
    toast(created ? `${s.name} is ready. Add your first items!` : "Settings saved");
    setTab(created ? (s.kind === "jewellery" || s.kind === "soap" ? "bulk" : "scan") : "inventory");
  }

  if (loadError)
    return (
      <div className="app">
        <div className="hero">
          <h1>Can't reach StockSnap</h1>
          <p className="muted">{loadError}</p>
          <button className="btn btn-primary" onClick={loadShops}>Try again</button>
        </div>
      </div>
    );

  if (shopList === null) return <div className="app"><div className="hero"><span className="spinner big" /></div></div>;

  // First run: no shops yet.
  if (shopList.length === 0 || !current)
    return (
      <div className="app">
        <ShopSetupPage first onDone={(s) => shopSaved(s, true)} />
        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    );

  const ai = health?.vision;
  const logo = logoUrl(current, logoVersion);
  return (
    <ShopContext.Provider value={{ shop: current, presets, logoVersion }}>
      <div className="app">
        <header>
          <div className="shop-switch">
            <button className="brand" onClick={() => setMenuOpen(!menuOpen)} aria-haspopup="menu" aria-expanded={menuOpen}>
              {logo ? <img src={logo} alt="" className="shop-logo" /> : <span className="shop-initial">{current.name[0]?.toUpperCase()}</span>}
              <span className="shop-name">{current.name}</span>
              <span className="caret">▾</span>
            </button>
            {menuOpen && (
              <>
                <div className="menu-scrim" onClick={() => setMenuOpen(false)} />
                <div className="menu" role="menu">
                  <div className="menu-label">Your shops</div>
                  {shopList.map((s) => (
                    <button key={s.slug} role="menuitem" className={s.slug === current.slug ? "on" : ""} onClick={() => switchTo(s.slug)}>
                      {s.has_logo ? (
                        <img className="shop-logo sm" src={logoUrl(s, logoVersion)} alt="" />
                      ) : (
                        <span className="shop-initial sm">{s.name[0]?.toUpperCase()}</span>
                      )}
                      {s.name}
                      {s.slug === current.slug && <span className="tick">✓</span>}
                    </button>
                  ))}
                  <hr />
                  <button role="menuitem" onClick={() => { setMenuOpen(false); setTab("new-shop"); }}>+ New shop</button>
                  <button role="menuitem" onClick={() => { setMenuOpen(false); setTab("settings"); }}>Shop settings</button>
                </div>
              </>
            )}
          </div>
          <span className={`ai-status ${ai?.available ? "on" : "off"}`} title={ai ? `${ai.model}: ${ai.detail}` : "App not reachable"}>
            ● AI {ai?.available ? "ready" : "off"}
          </span>
        </header>

        {health && !ai?.available && (
          <div className="banner no-print">Local AI isn't set up yet, so you'll type item details yourself. {ai?.detail}</div>
        )}

        {/* key: switching shop remounts every page so nothing from the old shop lingers */}
        <main key={current.slug}>
          {tab === "scan" && <ScanPage toast={toast} />}
          {tab === "bulk" && <BulkPage toast={toast} aiReady={!!ai?.available} />}
          {tab === "sell" && <SellPage toast={toast} />}
          {tab === "inventory" && <InventoryPage toast={toast} />}
          {tab === "reports" && <ReportsPage toast={toast} />}
          {tab === "photos" && <LabPage toast={toast} />}
          {tab === "settings" && (
            <ShopSetupPage
              existing={current}
              logoVersion={logoVersion}
              onCancel={() => setTab("inventory")}
              onDone={(s) => shopSaved(s, false)}
            />
          )}
          {tab === "new-shop" && <ShopSetupPage onCancel={() => setTab("scan")} onDone={(s) => shopSaved(s, true)} />}
        </main>

        <nav className="tabs no-print">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>

        {msg && <div className="toast" role="status">{msg}</div>}
      </div>
    </ShopContext.Provider>
  );
}
