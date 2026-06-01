import { useMemo, useState } from "react";
import { buildTree, descendantFiles, togglePath, type TreeNode } from "./fileTreeUtils";
import type { FileCoverage } from "../api/types";

interface Props {
  paths: string[];
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  active: string | null;
  onOpen: (path: string) => void;
  hits?: Record<string, number>;
  coverage?: Record<string, FileCoverage>;
}

const ICONS: Record<string, string> = {
  py: "🐍", ts: "🅣", tsx: "⚛️", js: "🅙", jsx: "⚛️", java: "☕", go: "🐹",
  rb: "💎", rs: "🦀", json: "🗎", md: "📝", html: "🌐", css: "🎨", yml: "⚙️", yaml: "⚙️",
};
const fileIcon = (name: string) => ICONS[name.split(".").pop()?.toLowerCase() ?? ""] ?? "📄";

export function FileTree(props: Props) {
  const root = useMemo(() => buildTree(props.paths), [props.paths]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const allSelected = props.paths.length > 0 && props.paths.every((f) => props.selected.has(f));

  const toggleCollapse = (path: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });

  const renderNode = (node: TreeNode, depth: number) => {
    const files = descendantFiles(root, node.path);
    const selectedCount = files.filter((f) => props.selected.has(f)).length;
    const checked = files.length > 0 && selectedCount === files.length;
    const indeterminate = selectedCount > 0 && selectedCount < files.length;
    const cov = props.coverage?.[node.path];
    const skipped = cov && !cov.agentReviewed;
    const isCollapsed = collapsed.has(node.path);

    return (
      <div key={node.path || "root"}>
        <div className={`tree-row ${props.active === node.path ? "active" : ""}`}
          style={{ paddingLeft: 4 + depth * 14 }}>
          <input
            type="checkbox"
            checked={checked}
            ref={(el) => { if (el) el.indeterminate = indeterminate; }}
            onChange={() => props.onSelectedChange(togglePath(root, props.selected, node.path))}
            aria-label={`select ${node.path}`}
          />
          {node.isDir ? (
            <button className="tree-label dir" onClick={() => toggleCollapse(node.path)}
              title={node.path}>
              <span className="chevron">{isCollapsed ? "▸" : "▾"}</span>
              <span className="ic">{isCollapsed ? "📁" : "📂"}</span>
              <span className="nm">{node.name}</span>
            </button>
          ) : (
            <button className="tree-label file" onClick={() => props.onOpen(node.path)} title={node.path}>
              <span className="chevron" />
              <span className="ic">{fileIcon(node.name)}</span>
              <span className="nm">{node.name}</span>
            </button>
          )}
          {props.hits?.[node.path] ? <span className="hit-badge" title="scanner findings">●{props.hits[node.path]}</span> : null}
          {skipped ? <span className="skip-tag">skipped</span> : null}
        </div>
        {!node.isDir || isCollapsed ? null : node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="file-tree">
      <label className="tree-row select-all">
        <input type="checkbox" checked={allSelected}
          onChange={() => props.onSelectedChange(togglePath(root, props.selected, ""))}
          aria-label="select all" />
        <span className="nm"><strong>{props.paths.length} file{props.paths.length === 1 ? "" : "s"}</strong> · select all</span>
      </label>
      {root.children.map((c) => renderNode(c, 0))}
    </div>
  );
}
