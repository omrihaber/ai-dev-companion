import { describe, expect, it } from "vitest";
import { buildTree, togglePath, descendantFiles } from "./fileTreeUtils";

const PATHS = ["app/auth.py", "app/db.py", "tests/test_a.py"];

describe("file tree logic", () => {
  it("builds nested nodes from flat paths", () => {
    const root = buildTree(PATHS);
    const app = root.children.find((c) => c.name === "app")!;
    expect(app.isDir).toBe(true);
    expect(app.children.map((c) => c.name).sort()).toEqual(["auth.py", "db.py"]);
  });

  it("descendantFiles returns all files under a dir", () => {
    const root = buildTree(PATHS);
    expect(descendantFiles(root, "app").sort()).toEqual(["app/auth.py", "app/db.py"]);
  });

  it("toggling a dir selects all its files; toggling again clears them", () => {
    const root = buildTree(PATHS);
    let sel = new Set<string>();
    sel = togglePath(root, sel, "app");
    expect(sel).toEqual(new Set(["app/auth.py", "app/db.py"]));
    sel = togglePath(root, sel, "app");
    expect(sel.size).toBe(0);
  });

  it("toggling a file toggles just that file", () => {
    const root = buildTree(PATHS);
    const sel = togglePath(root, new Set<string>(), "app/auth.py");
    expect(sel).toEqual(new Set(["app/auth.py"]));
  });
});
