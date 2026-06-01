export interface TreeNode {
  name: string;
  path: string;       // full path for files; dir prefix for dirs
  isDir: boolean;
  children: TreeNode[];
}

export function buildTree(paths: string[]): TreeNode {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };
  for (const p of [...paths].sort()) {
    const parts = p.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === part && c.isDir === !isFile);
      if (!child) {
        child = { name: part, path, isDir: !isFile, children: [] };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sortRec = (n: TreeNode) => {
    n.children.sort((a, b) => Number(b.isDir) - Number(a.isDir) || a.name.localeCompare(b.name));
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

function find(node: TreeNode, path: string): TreeNode | null {
  if (node.path === path) return node;
  for (const c of node.children) {
    const hit = find(c, path);
    if (hit) return hit;
  }
  return null;
}

export function descendantFiles(root: TreeNode, path: string): string[] {
  const node = path === "" ? root : find(root, path);
  if (!node) return [];
  if (!node.isDir) return [node.path];
  return node.children.flatMap((c) => descendantFiles(root, c.path));
}

export function togglePath(root: TreeNode, selected: Set<string>, path: string): Set<string> {
  const files = descendantFiles(root, path);
  const allSelected = files.every((f) => selected.has(f));
  const next = new Set(selected);
  for (const f of files) {
    if (allSelected) next.delete(f);
    else next.add(f);
  }
  return next;
}
