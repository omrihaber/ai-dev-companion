import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import JSZip from "jszip";
import { useReviewStream } from "../hooks/useReviewStream";
import { getFile } from "../api/client";
import type { FileCoverage, FileInput, Finding } from "../api/types";
import { FileTree } from "./FileTree";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";

const CEILING = 150;
const SAMPLE: FileInput = {
  path: "snippet.py",
  content:
    'def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n    cursor.execute(query)\n    return cursor.fetchall()\n',
  language: "python",
};
const EXT_LANG: Record<string, string> = { py: "python", ts: "typescript", tsx: "typescript", js: "javascript", java: "java" };
const langOf = (p: string) => EXT_LANG[p.split(".").pop() ?? ""] ?? "plaintext";

export function Workspace({ loadId }: { loadId?: string }) {
  const [files, setFiles] = useState<FileInput[]>([SAMPLE]);
  const [marked, setMarked] = useState<Set<string>>(new Set([SAMPLE.path]));
  const [active, setActive] = useState<string>(SAMPLE.path);
  const [viewContent, setViewContent] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const { start, rerun, load, progress, result, running, error, reviewId } = useReviewStream();

  useEffect(() => { if (loadId) void load(loadId); }, [loadId, load]);

  useEffect(() => {
    if (result?.coverage) {
      setMarked(new Set(result.coverage.files.filter((c) => c.agentReviewed).map((c) => c.path)));
    }
    // seed once when a review's coverage becomes available (load or completion)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.id]);

  useEffect(() => {
    if (!reviewId || !result) { setViewContent(null); return; }
    let on = true;
    void getFile(reviewId, active).then((c) => { if (on) setViewContent(c); }).catch(() => setViewContent(null));
    return () => { on = false; };
  }, [reviewId, result, active]);

  const localContent = useMemo(
    () => files.find((f) => f.path === active)?.content ?? "", [files, active]);
  const editorValue = result ? (viewContent ?? "") : localContent;

  const coverageByPath = useMemo<Record<string, FileCoverage>>(() => {
    const m: Record<string, FileCoverage> = {};
    result?.coverage?.files.forEach((c) => { m[c.path] = c; });
    return m;
  }, [result]);

  const hits = useMemo<Record<string, number>>(() => {
    const m: Record<string, number> = {};
    result?.findings.forEach((f) => {
      const file = f.location.file;
      if (file && f.sources.some((s) => s.type === "tool")) m[file] = (m[file] ?? 0) + 1;
    });
    return m;
  }, [result]);

  const allPaths = result?.coverage?.files.map((c) => c.path) ?? files.map((f) => f.path);
  const findingsForActive: Finding[] = (result?.findings ?? []).filter((f) => f.location.file === active);
  const grouped = useMemo<Record<string, Finding[]>>(() => {
    const m: Record<string, Finding[]> = {};
    (result?.findings ?? []).forEach((f) => {
      const k = f.location.file ?? "(unknown)";
      (m[k] ??= []).push(f);
    });
    return m;
  }, [result]);

  const onMount: OnMount = (editor) => { editorRef.current = editor; };
  const jumpTo = (line: number) => {
    const ed = editorRef.current;
    if (!ed) return;
    ed.revealLineInCenter(line); ed.setPosition({ lineNumber: line, column: 1 }); ed.focus();
  };

  const addFiles = useCallback(async (fileList: FileList) => {
    const next: FileInput[] = [];
    for (const f of Array.from(fileList)) {
      if (f.name.endsWith(".zip")) {
        const zip = await JSZip.loadAsync(f);
        for (const [path, entry] of Object.entries(zip.files)) {
          if (!entry.dir) next.push({ path, content: await entry.async("string"), language: langOf(path) });
        }
      } else {
        const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
        next.push({ path: rel, content: await f.text(), language: langOf(rel) });
      }
    }
    if (next.length) {
      setFiles(next);
      setMarked(new Set(next.map((f) => f.path)));
      setActive(next[0].path);
    }
  }, []);

  const review = () => start({ files, marked: [...marked] });

  return (
    <div className="workspace-3">
      <aside className="pane tree-pane">
        <div className="controls">
          <label className="upload-btn">
            Add files / folder
            <input type="file" multiple style={{ display: "none" }}
              // @ts-expect-error non-standard but widely supported
              webkitdirectory=""
              onChange={(e) => e.target.files && void addFiles(e.target.files)} />
          </label>
          <label className="upload-btn">
            Upload .zip
            <input type="file" accept=".zip" style={{ display: "none" }}
              onChange={(e) => e.target.files && void addFiles(e.target.files)} />
          </label>
        </div>
        <FileTree paths={allPaths} selected={marked} onSelectedChange={setMarked}
          active={active} onOpen={setActive} hits={hits} coverage={coverageByPath} />
      </aside>

      <section className="pane editor-pane">
        {result?.coverage && (
          <div className="coverage-banner">
            agents reviewed {result.coverage.filesAgentReviewed} / {result.coverage.filesTotal} ·
            scanners covered all {result.coverage.filesTotal}
            {reviewId && (
              <button className="rerun-btn" disabled={running}
                onClick={() => void rerun(reviewId, [...marked])}>Re-run ▶</button>
            )}
          </div>
        )}
        <div className="active-path">{active}</div>
        <Editor height="58vh" language={langOf(active)} theme="vs-dark" value={editorValue}
          onMount={onMount} options={{ minimap: { enabled: false }, fontSize: 13, readOnly: !!result }} />
        {!result && marked.size > 25 && (
          <div className="cost-warning">
            {marked.size} files marked for deep review — this may be slow/expensive
            {marked.size > CEILING ? " (over the limit; narrow your selection)" : ""}.
          </div>
        )}
        {!result && (
          <button className="review-btn" disabled={running} onClick={review}>
            {running ? "Reviewing…" : `Review ${marked.size} file(s) ▶`}
          </button>
        )}
      </section>

      <section className="pane findings-pane">
        <ProgressStepper progress={progress} />
        {error && <div className="error" role="alert">{error}</div>}
        {result && (
          <>
            <div className="summary">{result.summary}</div>
            <label className="show-all">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
              Show all files
            </label>
            {showAll
              ? Object.entries(grouped).map(([file, fs]) => (
                  <div key={file}>
                    <div className="group-file">{file}</div>
                    {fs.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
                  </div>
                ))
              : (
                <>
                  {findingsForActive.length === 0 && <p>No findings in this file.</p>}
                  {findingsForActive.map((f) => <FindingCard key={f.id} finding={f} onJump={jumpTo} />)}
                </>
              )}
          </>
        )}
      </section>
    </div>
  );
}
