import type { ReviewResult } from "./types";

export const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function createReview(language: string, code: string): Promise<string> {
  const res = await fetch(`${BASE}/api/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, code }),
  });
  if (!res.ok) throw new Error(`createReview failed: ${res.status} ${await res.text()}`);
  return (await res.json()).reviewId as string;
}

export async function getReview(id: string): Promise<ReviewResult> {
  const res = await fetch(`${BASE}/api/reviews/${id}`);
  if (!res.ok) throw new Error(`getReview failed: ${res.status}`);
  return (await res.json()) as ReviewResult;
}

export function eventsUrl(id: string): string {
  return `${BASE}/api/reviews/${id}/events`;
}
