import type { Finding } from "../api/types";

const SEV_COLOR: Record<string, string> = {
  critical: "#b00020", high: "#d33", medium: "#da0", low: "#0a7", info: "#789",
};

export function FindingCard({ finding, onJump }: { finding: Finding; onJump: (line: number) => void }) {
  return (
    <div className="finding-card" style={{ borderLeft: `4px solid ${SEV_COLOR[finding.severity]}` }}>
      <div className="finding-head">
        <span className="badge">{finding.category}</span>
        <span className="sev">{finding.severity}</span>
        <button className="loc" onClick={() => onJump(finding.location.startLine)}>
          line {finding.location.startLine} ↗
        </button>
      </div>
      <h4>{finding.title}</h4>
      <p>{finding.description}</p>
      <p className="reco">→ {finding.recommendation}</p>
      <div className="sources">
        sources:{" "}
        {finding.sources.map((s) =>
          s.url ? (
            <a key={s.name} href={s.url} target="_blank" rel="noreferrer" className="chip">◆ {s.name}</a>
          ) : (
            <span key={s.name} className="chip">◆ {s.name}</span>
          )
        )}
      </div>
    </div>
  );
}
