/**
 * Markdown -> plain-text renderer for AI answer cards.
 *
 * The backend's analytics card is authored as Markdown (`render_markdown`
 * in `app/analytics_agent.py` emits `**bold**`, backticks, `_italic_`, pipe
 * tables), but the chat card renders text into a plain `<p>` with no markdown
 * engine — so the raw `**`, `` ` `` and `_` markers surfaced literally to the
 * user ("**Loss: 1047000.0 …**").  Rather than pull a markdown engine into the
 * card, we render the small, known subset the backend emits back into clean
 * plain text (with optional Unicode emphasis), so the sentence a business owner
 * reads has no markup scars.
 */

/** Render one line of backend markdown to plain text (no leftover markers). */
function renderLine(line: string): string {
  let out = line;

  // Pipe tables: "| a | b |" + separator row -> "a  b".  The `---` filler row
  // becomes empty and is dropped entirely below.
  if (out.includes("|")) {
    const cells = out
      .split("|")
      .map((c) => c.trim())
      // A row of only dashes/fills is the separator -> contributes nothing.
      .filter((c) => c.length > 0 && !/^:?-{3,}:?$/.test(c));
    out = cells.join("  ");
  }

  // Bold **text** / __text__ -> text (kept for the emphasis pass).
  out = out.replace(/\*\*(.+?)\*\*/g, "$1").replace(/__(.+?)__/g, "$1");
  // Inline code `text` -> text (drop the ticks the user was seeing).
  out = out.replace(/`([^`]+)`/g, "$1");
  // Italic _text_ / *text_ -> text.
  out = out.replace(/_(.+?)_/g, "$1").replace(/\*([^*]+)\*/g, "$1");
  // Leading heading hashes, e.g. "## Total" -> "Total".
  out = out.replace(/^#{1,6}\s+/, "");
  // List bullets "- item" / "* item" -> "item" (leading marker only).
  out = out.replace(/^[-*]\s+/, "");
  return out.trim();
}

/**
 * Render a whole markdown answer to display text: markers stripped,
 * blank lines collapsed, and trailing whitespace per line removed.  Returns
 * "" for empty/whitespace-only input so the card renders nothing rather than
 * an empty box.
 */
export function mdToDisplayText(markdown: string | null | undefined): string {
  const raw = (markdown ?? "").replace(/\r\n?/g, "\n");
  if (!raw.trim()) return "";
  return raw
    .split("\n")
    .map(renderLine)
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n+$/, "")
    .trim();
}