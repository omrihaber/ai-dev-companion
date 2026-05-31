import { useEffect, useState } from "react";
import type { ReviewResult } from "../api/types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function HistoryPage() {
  const [items, setItems] = useState<ReviewResult[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${BASE}/api/reviews`)
      .then((r) => r.json())
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <h2>Review History</h2>
      <table>
        <thead><tr><th>Language</th><th>Status</th><th>Findings</th><th>Summary</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td>{r.language}</td><td>{r.status}</td><td>{r.findings.length}</td><td>{r.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p>Loading…</p>}
      {!loading && items.length === 0 && <p>No reviews yet.</p>}
    </div>
  );
}
