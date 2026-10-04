/**
 * professionalName — the frontend twin of `app/display_names.py`.
 *
 * Natural-language input arrives in whatever shape the user typed it; the ERP
 * must store master-data names with consistent display casing ("motorbike" →
 * "Motorbike") so documents and dropdowns read professionally — while never
 * rewriting casing the user set deliberately (acronyms like ABC/PVT, mixed
 * brands like iPhone).
 *
 * Rules (kept in lockstep with the Python side):
 * - fully-lowercase words get their first letter capitalised;
 * - ALL-CAPS acronyms and mixed-case tokens are untouched;
 * - connector words (and, for, of, the, …) stay lowercase mid-name;
 * - punctuation/digits/spacing preserved; only whitespace runs collapse.
 */

const CONNECTORS = new Set([
  "and", "or", "of", "for", "the", "at", "in", "on", "to", "with",
  "de", "del", "van", "von", "bin", "ibn",
]);

// Unicode letter runs with optional internal apostrophes; hyphens separate.
const WORD_RE = /[^\W\d_]+(?:['’][^\W\d_]+)*/gu;

export function professionalName(raw?: string | null): string {
  if (!raw) return "";
  const text = raw.replace(/\s+/g, " ").trim();
  if (!text) return "";

  let first = true;
  return text.replace(WORD_RE, (word) => {
    const lower = word.toLowerCase();
    const isFullyLower = word === lower;
    const out =
      isFullyLower && (first || !CONNECTORS.has(lower))
        ? lower.charAt(0).toUpperCase() + lower.slice(1)
        : word;
    first = false;
    return out;
  });
}
