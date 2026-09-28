import { useCallback, useEffect, useState } from "react";
import { api, type Expense, type Summary } from "../api";
import { isoDate, money, monthRange, toCents } from "../format";

const CATEGORIES = ["Materials", "Packaging", "Shipping", "Booth / market fees", "Marketing", "Equipment", "Other"];

export function ReportsPage({ toast }: { toast: (msg: string) => void }) {
  const now = new Date();
  const [ym, setYm] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [year, month] = ym.split("-").map(Number);
  const [start, end] = monthRange(year, month - 1);

  const [s, setS] = useState<Summary | null>(null);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [exp, setExp] = useState({ category: CATEGORIES[0], description: "", amount: "", spent_on: isoDate() });

  const load = useCallback(async () => {
    if (start > end) {
      setS(null);
      setExpenses([]);
      return;
    }
    const [sum, ex] = await Promise.all([api.summary(start, end), api.expenses(start, end)]);
    setS(sum);
    setExpenses(ex);
  }, [start, end]);

  useEffect(() => {
    load().catch((e) => toast(e.message));
  }, [load, toast]);

  async function addExpense(e: React.FormEvent) {
    e.preventDefault();
    const cents = toCents(exp.amount);
    if (!cents) return toast("Enter an amount, like 12.50");
    await api.addExpense({ category: exp.category, description: exp.description, amount_cents: cents, spent_on: exp.spent_on });
    setExp({ ...exp, description: "", amount: "" });
    toast("Expense added");
    load();
  }

  return (
    <section>
      <div className="toolbar">
        <input type="month" value={ym} max={isoDate().slice(0, 7)} onChange={(e) => e.target.value && setYm(e.target.value)} />
        <button className="btn btn-secondary" onClick={() => window.print()}>Print / PDF</button>
      </div>

      {s && (
        <>
          <div className="stats">
            <Stat label="Sales" value={money(s.revenue_cents)} sub={`${s.units_sold} items sold`} />
            <Stat label="Cost of goods" value={money(s.cogs_cents)} />
            <Stat label="Expenses" value={money(s.expenses_cents)} />
            <Stat label="Profit" value={money(s.net_profit_cents)} tone={s.net_profit_cents < 0 ? "neg" : "pos"} sub="sales − cost − expenses" />
          </div>
          <p className="muted">Stock on hand is worth {money(s.stock_value_cents)} at cost.</p>

          <h2>Best sellers</h2>
          <ul className="list">
            {s.top_items.map((t) => (
              <li key={t.item_id}>
                <span>{t.name}</span>
                <span className="muted">{t.units} sold</span>
                <span>{money(t.revenue_cents)}</span>
              </li>
            ))}
            {!s.top_items.length && <li className="muted">No sales this month.</li>}
          </ul>
        </>
      )}

      <h2>Expenses</h2>
      <form className="expense-form no-print" onSubmit={addExpense}>
        <select value={exp.category} onChange={(e) => setExp({ ...exp, category: e.target.value })}>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input placeholder="What for?" value={exp.description} onChange={(e) => setExp({ ...exp, description: e.target.value })} />
        <input placeholder="$" inputMode="decimal" value={exp.amount} onChange={(e) => setExp({ ...exp, amount: e.target.value })} />
        <input type="date" value={exp.spent_on} onChange={(e) => setExp({ ...exp, spent_on: e.target.value })} />
        <button className="btn btn-primary">Add</button>
      </form>
      <ul className="list">
        {expenses.map((x) => (
          <li key={x.id}>
            <span>
              {x.spent_on} · {x.category}
              {x.description && ` — ${x.description}`}
            </span>
            <span>{money(x.amount_cents)}</span>
            <button className="link no-print" onClick={() => api.deleteExpense(x.id).then(load)}>remove</button>
          </li>
        ))}
        {!expenses.length && <li className="muted">No expenses logged this month.</li>}
      </ul>

      <h2 className="no-print">Download</h2>
      <div className="actions no-print">
        <a className="btn btn-secondary" href={api.exportUrl("summary", start, end)}>Summary CSV</a>
        <a className="btn btn-secondary" href={api.exportUrl("sales", start, end)}>Sales CSV</a>
        <a className="btn btn-secondary" href={api.exportUrl("expenses", start, end)}>Expenses CSV</a>
        <a className="btn btn-secondary" href="/api/backup">Full backup (.zip)</a>
      </div>
      <p className="muted small">
        StockSnap doesn't calculate tax. Give these CSVs to your accountant or import them into your tax software.
      </p>
    </section>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "pos" | "neg" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}
