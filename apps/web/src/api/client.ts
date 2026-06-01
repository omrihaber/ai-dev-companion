import type { CreateReviewBody, ModelsResponse, ReviewResult } from "./types";

export const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function createReview(body: CreateReviewBody): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createReview failed: ${res.status} ${await res.text()}`);
  return (await res.json()).reviewId as string;
}

export async function rerunReview(id: string, marked: string[], model?: string): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews/${id}/rerun`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ marked, model }),
  });
  if (!res.ok) throw new Error(`rerun failed: ${res.status}`);
  return (await res.json()).reviewId as string;
}

export async function getModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}/api/models`);
  if (!res.ok) throw new Error(`getModels failed: ${res.status}`);
  return (await res.json()) as ModelsResponse;
}

export async function getFile(id: string, path: string): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews/${id}/file?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`getFile failed: ${res.status}`);
  return (await res.json()).content as string;
}

export async function getReview(id: string): Promise<ReviewResult> {
  const res = await fetch(`${BASE}/api/reviews/${id}`);
  if (!res.ok) throw new Error(`getReview failed: ${res.status}`);
  return (await res.json()) as ReviewResult;
}

export function eventsUrl(id: string): string {
  return `${BASE}/api/reviews/${id}/events`;
}
