import type { ProgressEvent } from "../api/types";

const STAGES = ["validating", "analyzing", "enriching", "finalizing", "done"] as const;

export function ProgressStepper({ progress }: { progress: ProgressEvent | null }) {
  const current = progress?.stage ?? "queued";
  const idx = STAGES.indexOf(current as (typeof STAGES)[number]);
  const subStatus = progress?.subStatus ?? {};  // tolerate events without subStatus
  return (
    <div className="stepper" role="status" aria-label="review progress">
      {STAGES.map((s, i) => (
        <span key={s} className={`step ${i <= idx ? "active" : ""}`}>
          {i < idx || current === "done" ? "✔" : i === idx ? "⟳" : "·"} {s}
        </span>
      ))}
      {Object.keys(subStatus).length > 0 && (
        <div className="substatus">
          {Object.entries(subStatus).map(([k, v]) => (
            <span key={k} className="chip">{k}: {v}</span>
          ))}
        </div>
      )}
    </div>
  );
}
