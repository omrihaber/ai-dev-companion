import { describe, expect, it, vi, beforeEach } from "vitest";
import { createReview, getFile, getReview, rerunReview } from "./client";

beforeEach(() => { vi.restoreAllMocks(); });

describe("api client", () => {
  it("getReview throws on 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    await expect(getReview("missing")).rejects.toThrow();
  });
});

describe("multi-file client", () => {
  it("createReview posts files + marked and returns id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ reviewId: "r1" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const id = await createReview({ files: [{ path: "a.py", content: "x" }], marked: ["a.py"] });
    expect(id).toBe("r1");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.files[0].path).toBe("a.py");
    expect(body.marked).toEqual(["a.py"]);
  });

  it("getFile fetches file content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ path: "a.py", content: "hello" }),
    }));
    expect(await getFile("r1", "a.py")).toBe("hello");
  });

  it("rerunReview posts marks and returns new id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ reviewId: "r2" }),
    }));
    expect(await rerunReview("r1", ["a.py"])).toBe("r2");
  });
});
