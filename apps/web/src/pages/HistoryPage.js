import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export function HistoryPage() {
    const [items, setItems] = useState([]);
    useEffect(() => {
        fetch(`${BASE}/api/reviews`).then((r) => r.json()).then(setItems).catch(() => setItems([]));
    }, []);
    return (_jsxs("div", { style: { padding: 16 }, children: [_jsx("h2", { children: "Review History" }), _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Language" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Findings" }), _jsx("th", { children: "Summary" })] }) }), _jsx("tbody", { children: items.map((r) => (_jsxs("tr", { children: [_jsx("td", { children: r.language }), _jsx("td", { children: r.status }), _jsx("td", { children: r.findings.length }), _jsx("td", { children: r.summary })] }, r.id))) })] }), items.length === 0 && _jsx("p", { children: "No reviews yet." })] }));
}
