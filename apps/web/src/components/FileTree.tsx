import { useMemo } from "react";
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

export function FileTree(props: Props) {
  const root = useMemo(() => buildTree(props.paths), [props.paths]);
  const allFiles = props.paths;
  const allSelected = allFiles.length > 0 && allFiles.every((f) => props.selected.has(f));

  const renderNode = (node: TreeNode, depth: number) => {
    const files = descendantFiles(root, node.path);
    const selectedCount = files.filter((f) => props.selected.has(f)).length;
    const checked = files.length > 0 && selectedCount === files.length;
    const indeterminate = selectedCount > 0 && selectedCount < files.length;
    const cov = props.coverage?.[node.path];
    const skipped = cov && !cov.agentReviewed;
    return (
      <div key={node.path || "root"}>
        <div className="tree-row" style={{ paddingLeft: depth * 14 }}>
          <input
            type="checkbox"
            checked={checked}
            ref={(el) => { if (el) el.indeterminate = indeterminate; }}
            onChange={() => props.onSelectedChange(togglePath(root, props.selected, node.path))}
            aria-label={`select ${node.path}`}
          />
          {node.isDir ? (
            <span className="tree-dir">{node.name}/</span>
          ) : (
            <button className={`tree-file ${props.active === node.path ? "active" : ""}`}
              onClick={() => props.onOpen(node.path)}>
              {node.name}
            </button>
          )}
          {props.hits?.[node.path] ? <span className="hit-badge">●{props.hits[node.path]}</span> : null}
          {skipped ? <span className="skip-tag">not deep-reviewed</span> : null}
        </div>
        {node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="file-tree">
      <label className="tree-row select-all">
        <input type="checkbox" checked={allSelected}
          onChange={() => props.onSelectedChange(togglePath(root, props.selected, ""))}
          aria-label="select all" />
        <strong>Select all</strong>
      </label>
      {root.children.map((c) => renderNode(c, 0))}
    </div>
  );
}
