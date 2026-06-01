import { useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useReviewStream } from "../hooks/useReviewStream";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";
import { ModelPicker } from "./ModelPicker";

// The simple single-snippet flow (assignment requirement): pick a language, paste one file, review.
const LANGUAGES = ["python", "typescript", "javascript", "java", "go", "rust", "bash"];
const EXT: Record<string, string> = {
  python: "py", typescript: "ts", javascript: "js", java: "java", go: "go", rust: "rs", bash: "sh",
};
const LANG_ICON: Record<string, string> = {
  python: "🐍", typescript: "🔷", javascript: "🟨", java: "☕", go: "🐹", rust: "🦀", bash: "🐚",
};
// Monaco's language id for bash is "shell"; the rest match our ids.
const monacoLang = (l: string) => (l === "bash" ? "shell" : l);
const SAMPLE =
  'def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n' +
  "    cursor.execute(query)\n    return cursor.fetchall()\n";

export function SnippetReview() {
  const [language, setLanguage] = useState("python");
  const [model, setModel] = useState("");
  const [code, setCode] = useState(SAMPLE);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const { start, progress, result, running, error } = useReviewStream();

  const onMount: OnMount = (editor) => { editorRef.current = editor; };
  const jumpTo = (line: number) => {
    const ed = editorRef.current;
    if (!ed) return;
    ed.revealLineInCenter(line);
    ed.setPosition({ lineNumber: line, column: 1 });
    ed.focus();
  };

  const review = () => {
    const path = `snippet.${EXT[language] ?? "txt"}`;
    start({ files: [{ path, content: code, language }], marked: [path], model: model || undefined });
  };

  return (
    <div className="workspace">
      <section className="pane editor-pane">
        <div className="controls">
          <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="language">
            {LANGUAGES.map((l) => <option key={l} value={l}>{LANG_ICON[l] ?? "📄"} {l}</option>)}
          </select>
          <ModelPicker value={model} onChange={setModel} />
        </div>
        <Editor height="60vh" language={monacoLang(language)} theme="vs-dark" value={code} onMount={onMount}
          onChange={(v) => setCode(v ?? "")}
          options={{ minimap: { enabled: false }, fontSize: 13, padding: { top: 10 } }} />
        <button className="review-btn" disabled={running} onClick={review}>
          {running ? "Reviewing…" : "Review Code ▶"}
        </button>
      </section>

      <section className="pane findings-pane">
        <ProgressStepper progress={progress} />
        {error && <div className="error" role="alert">{error}</div>}
        {result && (
          <>
            <div className="summary">{result.summary}</div>
            {result.findings.length === 0 && <p>No issues found 🎉</p>}
            {result.findings.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
          </>
        )}
      </section>
    </div>
  );
}
