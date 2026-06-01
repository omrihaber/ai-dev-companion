import type { Finding } from "../api/types";

const SEV_COLOR: Record<string, string> = {
  critical: "#ff5d6c", high: "#ff8359", medium: "#ffcc66", low: "#4ad6a8", info: "#7aa2f7",
};

export function FindingCard({ finding, onJump }: { finding: Finding; onJump: (line: number) => void }) {
  return (
    <div className="finding-card" style={{ borderLeft: `4px solid ${SEV_COLOR[finding.severity]}` }}>
      <div className="finding-head">
        <span className="badge">{finding.category}</span>
        <span className="sev" style={{ color: SEV_COLOR[finding.severity] }}>{finding.severity}</span>
        <button className="loc" onClick={() => onJump(finding.location.startLine)}>
          line {finding.location.startLine} ↗
        </button>
      </div>
      <h4>{finding.title}</h4>
      <p>{finding.description}</p>
      <p className="reco">→ {finding.recommendation}</p>
      <div className="sources">
        sources:{" "}
        {finding.sources.map((s) => {
          const isAgent = s.type === "agent";
          const icon = isAgent ? "🤖" : "🔧";
          const cls = `chip ${isAgent ? "chip-agent" : "chip-tool"}`;
          const title = isAgent ? "AI agent" : "static scanner";
          return s.url ? (
            <a key={s.name} href={s.url} target="_blank" rel="noreferrer" className={cls} title={title}>
              {icon} {s.name}
            </a>
          ) : (
            <span key={s.name} className={cls} title={title}>{icon} {s.name}</span>
          );
        })}
      </div>
    </div>
  );
}
