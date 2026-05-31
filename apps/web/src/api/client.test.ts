import { describe, expect, it, vi, beforeEach } from "vitest";
import { createReview, getReview } from "./client";

beforeEach(() => { vi.restoreAllMocks(); });

describe("api client", () => {
  it("createReview posts code and returns reviewId", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ reviewId: "r1", status: "queued" }), { status: 202 })));
    const id = await createReview("python", "x=1");
    expect(id).toBe("r1");
  });

  it("getReview throws on 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    await expect(getReview("missing")).rejects.toThrow();
  });
});
