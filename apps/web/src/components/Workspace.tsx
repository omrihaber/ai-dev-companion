import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useReviewStream } from "../hooks/useReviewStream";
import { getFile } from "../api/client";
import type { FileCoverage, FileInput, Finding } from "../api/types";
import { FileTree } from "./FileTree";
import { ProgressStepper } from "./ProgressStepper";
import { FindingCard } from "./FindingCard";
import { entriesToInputs, filesToInputs, langOf } from "./ingest";

const CEILING = 150;
const SAMPLE: FileInput = {
  path: "snippet.py",
  content:
    'def get_user_data(user_id):\n    query = "SELECT * FROM users WHERE id = " + str(user_id)\n    cursor.execute(query)\n    return cursor.fetchall()\n',
  language: "python",
};

export function Workspace({ loadId }: { loadId?: string }) {
  const [files, setFiles] = useState<FileInput[]>([SAMPLE]);
  const [marked, setMarked] = useState<Set<string>>(new Set([SAMPLE.path]));
  const [active, setActive] = useState<string>(SAMPLE.path);
  const [viewContent, setViewContent] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const { start, rerun, load, progress, result, running, error, reviewId } = useReviewStream();

  useEffect(() => { if (loadId) void load(loadId); }, [loadId, load]);

  // Seed the tree marks once per review (load or completion) from its coverage, so Re-run
  // re-marks exactly the files that were deep-reviewed.
  useEffect(() => {
    if (result?.coverage) {
      setMarked(new Set(result.coverage.files.filter((c) => c.agentReviewed).map((c) => c.path)));
    }
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

  const applyInputs = useCallback((next: FileInput[]) => {
    if (!next.length) {
      setUploadMsg("No reviewable files found (binaries, deps, and large files are ignored).");
      return;
    }
    const sorted = [...next].sort((a, b) => a.path.localeCompare(b.path));
    setUploadMsg(`Loaded ${sorted.length} file${sorted.length === 1 ? "" : "s"}.`);
    setFiles(sorted);
    setMarked(new Set(sorted.map((f) => f.path)));
    setActive(sorted[0].path);
  }, []);

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    // Capture entries SYNCHRONOUSLY — webkitGetAsEntry()/items are cleared once the handler yields.
    const dt = e.dataTransfer;
    const entries = Array.from(dt.items)
      .filter((it) => it.kind === "file")
      .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));
    const fallback = Array.from(dt.files);
    setUploadMsg("Reading dropped files…");
    void (async () => {
      try {
        applyInputs(await entriesToInputs(entries, fallback));
      } catch (err) {
        setUploadMsg(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    })();
  }, [applyInputs]);

  const review = () => start({ files, marked: [...marked] });

  return (
    <div className="workspace-3">
      <aside className={`pane tree-pane ${dragActive ? "drag-active" : ""}`}
        onDragOver={(e) => { e.preventDefault(); if (!dragActive) setDragActive(true); }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setDragActive(false); }}
        onDrop={(e) => void onDrop(e)}>
        <div className="controls">
          <label className="upload-btn" title="Add individual files">
            📄 Files
            <input type="file" multiple style={{ display: "none" }}
              onChange={(e) => e.target.files && void filesToInputs(e.target.files).then(applyInputs)} />
          </label>
          <label className="upload-btn" title="Add a whole folder">
            📁 Folder
            <input type="file" multiple style={{ display: "none" }}
              // @ts-expect-error webkitdirectory is non-standard but widely supported
              webkitdirectory=""
              onChange={(e) => e.target.files && void filesToInputs(e.target.files).then(applyInputs)} />
          </label>
          <label className="upload-btn" title="Add a .zip archive">
            🗜 .zip
            <input type="file" accept=".zip" style={{ display: "none" }}
              onChange={(e) => e.target.files && void filesToInputs(e.target.files).then(applyInputs)} />
          </label>
        </div>
        {uploadMsg && <div className="upload-msg">{uploadMsg}</div>}
        <FileTree paths={allPaths} selected={marked} onSelectedChange={setMarked}
          active={active} onOpen={setActive} hits={hits} coverage={coverageByPath} />
        <div className="drop-hint">Drag &amp; drop a folder or files here</div>
        {dragActive && <div className="drop-overlay">Drop to load files</div>}
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
