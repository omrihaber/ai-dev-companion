export type Category = "security" | "performance" | "logic" | "style" | "syntax";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type ReviewStatus =
  | "queued" | "validating" | "analyzing" | "enriching" | "finalizing" | "done" | "failed";

export interface Location { file?: string; startLine: number; endLine: number; startCol?: number; endCol?: number; }
export interface Source { type: "agent" | "tool"; name: string; confidence?: number; ruleId?: string; url?: string; }
export interface Finding {
  id: string; category: Category; severity: Severity; title: string;
  description: string; recommendation: string; location: Location; sources: Source[]; codeSnippet?: string;
}
export interface ReviewResult {
  id: string; status: ReviewStatus; language: string; model: string;
  findings: Finding[]; summary: string; createdAt: string; durationMs?: number; error?: string;
}
export interface ProgressEvent {
  reviewId: string; stage: ReviewStatus; percent?: number; subStatus: Record<string, string>; message?: string;
}
