import { useState } from "react";
import { SnippetReview } from "./SnippetReview";
import { Workspace } from "./Workspace";

// Two ways to start a review: a simple single Snippet (language dropdown), or a multi-file Project.
export function NewReview() {
  const [mode, setMode] = useState<"snippet" | "project">("snippet");
  return (
    <div>
      <div className="tabbar" role="tablist">
        <button role="tab" aria-selected={mode === "snippet"}
          className={`tab ${mode === "snippet" ? "active" : ""}`} onClick={() => setMode("snippet")}>
          Snippet
        </button>
        <button role="tab" aria-selected={mode === "project"}
          className={`tab ${mode === "project" ? "active" : ""}`} onClick={() => setMode("project")}>
          Project (multi-file)
        </button>
      </div>
      {mode === "snippet" ? <SnippetReview /> : <Workspace />}
    </div>
  );
}
