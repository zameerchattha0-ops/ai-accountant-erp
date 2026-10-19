import { describe, expect, it } from "vitest";

import { mdToDisplayText } from "@/lib/ai/markdown";

/**
 * The analytics card is authored as Markdown (`render_markdown` in
 * `app/analytics_agent.py`) but rendered into a plain `<p>` with no markdown
 * engine, so `**`, backticks and `_` surfaced literally. These pin the
 * plain-text rendering of exactly the shapes the backend emits.
 */
describe("mdToDisplayText", () => {
  it("strips the bold markers off a computed headline", () => {
    expect(
      mdToDisplayText("**Loss: 1047000.0 (credit) minus 1055333.33 = -8333.33**")
    ).toBe("Loss: 1047000.0 (credit) minus 1055333.33 = -8333.33");
  });

  it("drops backticks and the leading bullet on an aggregate line", () => {
    expect(
      mdToDisplayText("- sum(credit) = **1047000.0** (7 rows from `journal_lines`)")
    ).toBe("sum(credit) = 1047000.0 (7 rows from journal_lines)");
  });

  it("removes italic markers from caveat lines", () => {
    expect(
      mdToDisplayText("_difference computed in Python from the two aggregates (never by the model)_")
    ).toBe("difference computed in Python from the two aggregates (never by the model)");
  });

  it("renders a pipe table as plain cells and drops the separator row", () => {
    const md = [
      "**Top expenses**",
      "",
      "| account | total |",
      "|---|---|",
      "| Rent | 400000 |",
      "| Salaries | 250000 |",
    ].join("\n");
    // The separator row renders to "" and stays as a blank line inside the
    // block (only 3+ consecutive blanks collapse), so it reads as a divider.
    expect(mdToDisplayText(md)).toBe(
      ["Top expenses", "", "account  total", "", "Rent  400000", "Salaries  250000"].join("\n")
    );
  });

  it("keeps line structure, collapses 3+ blank lines and trims trailing newlines", () => {
    expect(mdToDisplayText("a\n\n\n\nb\n\n")).toBe("a\n\nb");
  });

  it("returns empty string for empty / whitespace input", () => {
    expect(mdToDisplayText("")).toBe("");
    expect(mdToDisplayText("   \n  ")).toBe("");
    expect(mdToDisplayText(null)).toBe("");
    expect(mdToDisplayText(undefined)).toBe("");
  });
});