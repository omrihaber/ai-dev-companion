import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FindingCard } from "./FindingCard";
import type { Finding } from "../api/types";

const finding: Finding = {
  id: "f1", category: "security", severity: "high", title: "SQL injection",
  description: "String concat", recommendation: "Use params",
  location: { startLine: 2, endLine: 2 },
  sources: [{ type: "agent", name: "core-reviewer" }, { type: "tool", name: "semgrep", url: "http://x" }],
};

describe("FindingCard", () => {
  it("renders category, severity, location, recommendation and source citations", () => {
    render(<FindingCard finding={finding} onJump={() => {}} />);
    expect(screen.getByText(/SQL injection/)).toBeInTheDocument();
    expect(screen.getByText(/security/i)).toBeInTheDocument();
    expect(screen.getByText(/line 2/i)).toBeInTheDocument();
    expect(screen.getByText(/core-reviewer/)).toBeInTheDocument();
    expect(screen.getByText(/semgrep/)).toBeInTheDocument();
  });

  it("calls onJump with the start line when location clicked", () => {
    const onJump = vi.fn();
    render(<FindingCard finding={finding} onJump={onJump} />);
    fireEvent.click(screen.getByText(/line 2/i));
    expect(onJump).toHaveBeenCalledWith(2);
  });
});
