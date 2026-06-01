import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BASE } from "../api/client";
import type { ReviewResult } from "../api/types";

type Row = ReviewResult & { fileCount?: number };

export function HistoryPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${BASE}/api/reviews`)
      .then((r) => r.json()).then(setItems)
      .catch(() => setItems([])).finally(() => setLoading(false));
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <h2>Review History</h2>
      <table>
        <thead><tr><th>Language</th><th>Files</th><th>Status</th><th>Findings</th><th>Summary</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/review/${r.id}`}>{r.language}</Link></td>
              <td>{r.fileCount ?? 0}</td>
              <td>{r.status}</td>
              <td>{r.findings.length}</td>
              <td>{r.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p>Loading…</p>}
      {!loading && items.length === 0 && <p>No reviews yet.</p>}
    </div>
  );
}
