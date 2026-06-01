import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BASE } from "../api/client";
import type { Category, ReviewResult } from "../api/types";

type Row = ReviewResult & { fileCount?: number };

// Category columns with descriptive emoji headers (matches the agent categories).
const CATEGORIES: { key: Category; emoji: string; label: string }[] = [
  { key: "security", emoji: "🔒", label: "Security" },
  { key: "performance", emoji: "⚡", label: "Performance" },
  { key: "logic", emoji: "🧠", label: "Logic" },
  { key: "quality", emoji: "✨", label: "Quality" },
  { key: "docs", emoji: "📝", label: "Docs" },
  { key: "tests", emoji: "🧪", label: "Tests" },
  { key: "syntax", emoji: "🔧", label: "Syntax" },
];

function countByCategory(r: Row): Record<string, number> {
  const m: Record<string, number> = {};
  for (const f of r.findings) m[f.category] = (m[f.category] ?? 0) + 1;
  return m;
}

const fmtTime = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
};

export function HistoryPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${BASE}/api/reviews`)
      .then((r) => r.json()).then(setItems)
      .catch(() => setItems([])).finally(() => setLoading(false));
  }, []);

  const rows = useMemo(() => items.map((r) => ({ r, counts: countByCategory(r) })), [items]);

  return (
    <div style={{ padding: 16 }}>
      <h2>📜 Review History</h2>
      <table className="history-table">
        <thead>
          <tr>
            <th>🕒 Time</th>
            <th>💻 Language</th>
            <th>📁 Files</th>
            <th>🚦 Status</th>
            {CATEGORIES.map((c) => <th key={c.key} title={c.label}>{c.emoji}</th>)}
            <th>Σ Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ r, counts }) => (
            <tr key={r.id}>
              <td><Link to={`/review/${r.id}`}>{fmtTime(r.createdAt)}</Link></td>
              <td>{r.language}</td>
              <td>{r.fileCount ?? 0}</td>
              <td>{r.status}</td>
              {CATEGORIES.map((c) => (
                <td key={c.key} className={counts[c.key] ? "has" : "zero"}>{counts[c.key] ?? 0}</td>
              ))}
              <td><strong>{r.findings.length}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p>Loading…</p>}
      {!loading && items.length === 0 && <p>No reviews yet.</p>}
    </div>
  );
}
