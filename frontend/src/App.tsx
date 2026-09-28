import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Health } from "./api";
import { InventoryPage } from "./pages/InventoryPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ScanPage } from "./pages/ScanPage";
import { SellPage } from "./pages/SellPage";

const TABS = [
  { id: "scan", label: "Add stock" },
  { id: "sell", label: "Sell" },
  { id: "inventory", label: "Inventory" },
  { id: "reports", label: "Money" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<Tab>(() => {
    const h = location.hash.slice(1);
    return (TABS.find((t) => t.id === h)?.id ?? "scan") as Tab;
  });
  const [health, setHealth] = useState<Health | null>(null);
  const [msg, setMsg] = useState("");

  const timer = useRef<number>(undefined);
  const toast = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(""), 3500);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    history.replaceState(null, "", `#${tab}`);
  }, [tab]);

  const ai = health?.vision;
  return (
    <div className="app">
      <header>
        <div className="brand">
          <img src="/icon.svg" alt="" width={30} height={30} />
          StockSnap
        </div>
        <span
          className={`ai-status ${ai?.available ? "on" : "off"}`}
          title={ai ? `${ai.model}: ${ai.detail}` : "App not reachable"}
        >
          ● AI {ai?.available ? "ready" : "off"}
        </span>
      </header>

      {health && !ai?.available && (
        <div className="banner no-print">
          Local AI isn't set up yet, so you'll type item details yourself. {ai?.detail}
        </div>
      )}

      <main>
        {tab === "scan" && <ScanPage toast={toast} />}
        {tab === "sell" && <SellPage toast={toast} />}
        {tab === "inventory" && <InventoryPage toast={toast} />}
        {tab === "reports" && <ReportsPage toast={toast} />}
      </main>

      <nav className="tabs no-print">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {msg && (
        <div className="toast" role="status">
          {msg}
        </div>
      )}
    </div>
  );
}
