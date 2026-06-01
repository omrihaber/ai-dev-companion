import { useEffect, useState } from "react";
import { getModels } from "../api/client";

// Dropdown of the configured provider's models. Provider + key come from the server (.env);
// this only chooses which model the review uses. Defaults to the provider's current model.
export function ModelPicker({ value, onChange }: { value: string; onChange: (m: string) => void }) {
  const [models, setModels] = useState<string[]>([]);
  useEffect(() => {
    getModels()
      .then((r) => {
        setModels(r.models);
        if (!value && r.current) onChange(r.current);
      })
      .catch(() => setModels([]));
  }, []); // fetch once on mount

  return (
    <label className="model-pick">
      <span>🤖</span>
      <select aria-label="model" value={value} onChange={(e) => onChange(e.target.value)}>
        {value && !models.includes(value) ? <option value={value}>{value}</option> : null}
        {models.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
    </label>
  );
}
