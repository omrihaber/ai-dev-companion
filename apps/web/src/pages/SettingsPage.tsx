import { BASE } from "../api/client";

export function SettingsPage() {
  return (
    <div style={{ padding: 16 }}>
      <h2>Settings — Model Provider</h2>
      <p>The active model provider is configured via environment variables (see <code>.env.example</code>):</p>
      <ul>
        <li><code>ADC_MODEL_PROVIDER</code> — <code>ollama</code> (default) | <code>openai</code> <em>(Anthropic adapter lands in Inc 2)</em></li>
        <li><code>ADC_MODEL</code> — e.g. <code>qwen2.5-coder:7b</code></li>
        <li>BYO: set <code>ADC_OPENAI_BASE_URL</code> + <code>ADC_OPENAI_API_KEY</code></li>
      </ul>
      <p>API base: <code>{BASE}</code>. An in-app editable form arrives in Inc 2 (model abstraction).</p>
    </div>
  );
}
