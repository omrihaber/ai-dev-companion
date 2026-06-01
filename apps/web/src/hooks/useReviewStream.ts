import { useCallback, useRef, useState } from "react";
import { createReview, eventsUrl, getReview } from "../api/client";
import type { ProgressEvent, ReviewResult } from "../api/types";

const TERMINAL = new Set(["done", "failed"]);

export function useReviewStream() {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const start = useCallback(async (language: string, code: string) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      const id = await createReview({ files: [{ path: `snippet.${language === 'typescript' ? 'ts' : language === 'java' ? 'java' : 'py'}`, content: code, language }], marked: [] });
      const es = new EventSource(eventsUrl(id));
      esRef.current = es;
      let finished = false;

      // Fetch the final result exactly once — triggered by either a terminal progress event
      // (done/failed) or the `complete` event, whichever the browser delivers first. This is
      // resilient to the SSE connection closing immediately after a fast review.
      const finish = async () => {
        if (finished) return;
        finished = true;
        es.close();
        const r = await getReview(id);
        setResult(r); setRunning(false);
        if (r.status === "failed") setError(r.error ?? "review failed");
      };

      es.addEventListener("progress", (e) => {
        const ev = JSON.parse((e as MessageEvent).data) as ProgressEvent;
        setProgress(ev);
        if (TERMINAL.has(ev.stage)) void finish();
      });
      es.addEventListener("complete", () => void finish());
      es.onerror = () => {
        if (finished) return; // connection closed after we already have the result — ignore
        es.close(); setRunning(false); setError("connection lost");
      };
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, []);

  return { start, progress, result, running, error };
}
