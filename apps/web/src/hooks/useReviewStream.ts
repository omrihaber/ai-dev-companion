import { useCallback, useRef, useState } from "react";
import { createReview, eventsUrl, getReview, rerunReview } from "../api/client";
import type { CreateReviewBody, ProgressEvent, ReviewResult } from "../api/types";

const TERMINAL = new Set(["done", "failed"]);

export function useReviewStream() {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const stream = useCallback((id: string) => {
    setReviewId(id);
    const es = new EventSource(eventsUrl(id));
    esRef.current = es;
    let finished = false;
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
      if (finished) return;
      es.close(); setRunning(false); setError("connection lost");
    };
  }, []);

  const start = useCallback(async (body: CreateReviewBody) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      stream(await createReview(body));
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, [stream]);

  const rerun = useCallback(async (id: string, marked: string[]) => {
    setProgress(null); setResult(null); setError(null); setRunning(true);
    try {
      stream(await rerunReview(id, marked));
    } catch (err) {
      setRunning(false); setError(err instanceof Error ? err.message : "unknown error");
    }
  }, [stream]);

  const load = useCallback(async (id: string) => {
    setProgress(null); setError(null); setRunning(false);
    setReviewId(id);
    setResult(await getReview(id));
  }, []);

  return { start, rerun, load, progress, result, running, error, reviewId };
}
