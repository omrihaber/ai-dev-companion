// Client-side ingestion: turn picked/dropped files (or a .zip) into FileInput[], mirroring the
// server's ignore denylist + caps so uploading a real repo doesn't choke on node_modules/binaries.
import JSZip from "jszip";
import type { FileInput } from "../api/types";

const IGNORE_DIRS = new Set([
  "node_modules", ".git", "dist", "build", "vendor", "__pycache__",
  ".next", ".turbo", ".venv", "venv", "coverage", ".idea", ".vscode",
]);
const IGNORE_EXT = new Set([
  "lock", "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", "pdf", "zip", "gz", "tar",
  "so", "dll", "exe", "bin", "woff", "woff2", "ttf", "eot", "map", "lockb",
]);
const MAX_FILE_BYTES = 512_000;

// Control chars (excluding tab \t, newline \n, carriage-return \r) signal a binary file.
// eslint-disable-next-line no-control-regex
const BINARY_RE = /[\x00-\x08\x0e-\x1f]/;
const isBinary = (s: string): boolean => BINARY_RE.test(s);

const EXT_LANG: Record<string, string> = {
  py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  java: "java", go: "go", rb: "ruby", rs: "rust", c: "c", h: "c", cpp: "cpp", cc: "cpp",
  cs: "csharp", php: "php", kt: "kotlin", sh: "bash", bash: "bash",
};
export const langOf = (p: string): string =>
  EXT_LANG[p.split(".").pop()?.toLowerCase() ?? ""] ?? "plaintext";

export function shouldIgnore(path: string): boolean {
  const norm = path.replace(/^\.?\//, "");
  if (norm.split("/").some((seg) => IGNORE_DIRS.has(seg))) return true;
  const name = norm.split("/").pop() ?? "";
  if (name === ".DS_Store" || name.endsWith(".min.js")) return true;
  return IGNORE_EXT.has(name.split(".").pop()?.toLowerCase() ?? "");
}

async function readOne(file: File, path: string): Promise<FileInput | null> {
  const norm = path.replace(/^\.?\//, "");
  if (shouldIgnore(norm) || file.size > MAX_FILE_BYTES) return null;
  const content = await file.text();
  if (isBinary(content)) return null;
  return { path: norm, content, language: langOf(norm) };
}

async function expandZip(file: File): Promise<FileInput[]> {
  const zip = await JSZip.loadAsync(file);
  const out: FileInput[] = [];
  for (const [path, entry] of Object.entries(zip.files)) {
    if (entry.dir || shouldIgnore(path)) continue;
    const content = await entry.async("string");
    if (!isBinary(content)) out.push({ path: path.replace(/^\.?\//, ""), content, language: langOf(path) });
  }
  return out;
}

/** Picked via <input> (folder upload uses webkitRelativePath) or a .zip. */
export async function filesToInputs(list: FileList | File[]): Promise<FileInput[]> {
  const out: FileInput[] = [];
  for (const f of Array.from(list)) {
    if (f.name.toLowerCase().endsWith(".zip")) {
      out.push(...(await expandZip(f)));
    } else {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      const fi = await readOne(f, rel);
      if (fi) out.push(fi);
    }
  }
  return out;
}

// ---- drag & drop (recurses dropped directories via the webkitGetAsEntry API) ----

interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (cb: (f: File) => void, err?: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (cb: (e: FsEntry[]) => void, err?: (e: unknown) => void) => void };
}

function entryFile(entry: FsEntry): Promise<File | null> {
  return new Promise((res) => (entry.file ? entry.file((f) => res(f), () => res(null)) : res(null)));
}

function readDir(entry: FsEntry): Promise<FsEntry[]> {
  const reader = entry.createReader?.();
  if (!reader) return Promise.resolve([]);
  const all: FsEntry[] = [];
  return new Promise((res) => {
    const pump = () =>
      reader.readEntries((batch) => {
        if (!batch.length) return res(all);
        all.push(...batch);
        pump(); // readEntries returns in chunks; keep calling until empty
      }, () => res(all));
    pump();
  });
}

async function walk(entry: FsEntry, base: string, out: FileInput[]): Promise<void> {
  const path = base ? `${base}/${entry.name}` : entry.name;
  if (shouldIgnore(path)) return;
  if (entry.isFile) {
    const f = await entryFile(entry);
    if (f) {
      const fi = await readOne(f, path);
      if (fi) out.push(fi);
    }
  } else if (entry.isDirectory) {
    for (const child of await readDir(entry)) await walk(child, path, out);
  }
}

// Opaque to callers — the FS entries captured synchronously in the drop handler.
export type DroppedEntry = unknown;

/** webkitGetAsEntry() MUST be called synchronously inside the drop event (the item list is
 * cleared once the handler yields), so the caller captures entries + the flat file list and
 * passes them here for async processing. Falls back to the flat list if the entries API is absent. */
export async function entriesToInputs(
  entries: DroppedEntry[], fallback: File[],
): Promise<FileInput[]> {
  const fsEntries = entries.filter((e): e is FsEntry => !!e);
  if (fsEntries.length) {
    const out: FileInput[] = [];
    for (const e of fsEntries) {
      if (e.isFile && e.name.toLowerCase().endsWith(".zip")) {
        const f = await entryFile(e);
        if (f) out.push(...(await expandZip(f)));
      } else {
        await walk(e, "", out);
      }
    }
    if (out.length) return out;
  }
  return filesToInputs(fallback); // no entries API, or entries yielded nothing
}
