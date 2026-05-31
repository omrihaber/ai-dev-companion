import { useCallback, useRef, useState } from "react";
import { createReview, eventsUrl, getReview } from "../api/client";
import type { ProgressEvent, ReviewResult } from "../api/types";

export function useReviewStream() {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const start = useCallback(async (language: string, code: string) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      const id = await createReview(language, code);
      const es = new EventSource(eventsUrl(id));
      esRef.current = es;
      es.addEventListener("progress", (e) => {
        const ev = JSON.parse((e as MessageEvent).data) as ProgressEvent;
        setProgress(ev);
      });
      es.addEventListener("complete", async () => {
        es.close();
        const r = await getReview(id);
        setResult(r); setRunning(false);
        if (r.status === "failed") setError(r.error ?? "review failed");
      });
      es.onerror = () => { es.close(); setRunning(false); setError("connection lost"); };
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, []);

  return { start, progress, result, running, error };
}
