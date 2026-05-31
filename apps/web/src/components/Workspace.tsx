import { useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useReviewStream } from "../hooks/useReviewStream";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";

const LANGUAGES = ["python", "typescript", "java"];
const SAMPLE = `def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n    cursor.execute(query)\n    return cursor.fetchall()\n`;

export function Workspace() {
  const [language, setLanguage] = useState("python");
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

  return (
    <div className="workspace">
      <section className="pane editor-pane">
        <div className="controls">
          <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="language">
            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <Editor height="60vh" language={language} value={code} onMount={onMount}
          onChange={(v) => setCode(v ?? "")} options={{ minimap: { enabled: false } }} />
        <button className="review-btn" disabled={running} onClick={() => start(language, code)}>
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
