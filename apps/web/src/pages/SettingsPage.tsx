import { useEffect, useState } from "react";
import { BASE } from "../api/client";

interface Settings { provider: string; model: string; baseUrl: string; hasKey: boolean; keyHint?: string; }
const PROVIDERS = ["openai", "ollama", "anthropic", "mock"];

export function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${BASE}/api/settings`).then((r) => r.json()).then(setS).catch(() => setS(null));
  }, []);

  if (!s) return <div style={{ padding: 16 }}>Loading settings…</div>;

  const save = async () => {
    setSaving(true);
    setStatus(null);
    const body: Record<string, string> = { provider: s.provider, model: s.model, baseUrl: s.baseUrl };
    if (apiKey) body.apiKey = apiKey;
    try {
      const r = await fetch(`${BASE}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`${r.status}`);
      setS(await r.json());
      setApiKey("");
      setStatus("Saved ✓ — applies to the next review.");
    } catch (e) {
      setStatus(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-form">
      <h2>⚙️ Settings — Model Provider</h2>
      <label>
        Provider
        <select value={s.provider} onChange={(e) => setS({ ...s, provider: e.target.value })}>
          {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      <label>
        Model
        <input value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })}
          placeholder="e.g. gpt-4o-mini" />
      </label>
      <label>
        API key
        <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
          placeholder={s.hasKey ? `set (${s.keyHint || "••••"}) — leave blank to keep` : "not set"} />
      </label>
      <label>
        Base URL <span className="muted">(optional)</span>
        <input value={s.baseUrl} onChange={(e) => setS({ ...s, baseUrl: e.target.value })}
          placeholder="https://api.openai.com/v1" />
      </label>
      <button className="review-btn" disabled={saving} onClick={save}>
        {saving ? "Saving…" : "Save"}
      </button>
      {status && <p className="settings-status">{status}</p>}
    </div>
  );
}
