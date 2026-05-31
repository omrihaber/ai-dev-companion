import type { ProgressEvent } from "../api/types";

const STAGES = ["validating", "analyzing", "enriching", "finalizing", "done"] as const;

export function ProgressStepper({ progress }: { progress: ProgressEvent | null }) {
  const current = progress?.stage ?? "queued";
  const idx = STAGES.indexOf(current as (typeof STAGES)[number]);
  return (
    <div className="stepper" role="status" aria-label="review progress">
      {STAGES.map((s, i) => (
        <span key={s} className={`step ${i <= idx ? "active" : ""}`}>
          {i < idx || current === "done" ? "✔" : i === idx ? "⟳" : "·"} {s}
        </span>
      ))}
      {progress && Object.keys(progress.subStatus).length > 0 && (
        <div className="substatus">
          {Object.entries(progress.subStatus).map(([k, v]) => (
            <span key={k} className="chip">{k}: {v}</span>
          ))}
        </div>
      )}
    </div>
  );
}
