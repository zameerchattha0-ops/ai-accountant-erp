import type { QuestionOption } from "@/lib/types/api";

/**
 * Chip-selection helpers for the clarification card.
 *
 * The backend sends the same choices TWICE for a single question — the
 * structured `question_options[0]` payload and the legacy `options` string
 * list — so rendering both produced every button twice.  These pure helpers
 * decide what each list contributes: the structured payload wins, the legacy
 * list only adds choices it does not already carry.
 */

/** A genuine answer option: non-empty and never the question itself. */
export function isAnswerOption(option: string): boolean {
  const text = (option ?? "").trim();
  return text.length > 0 && !text.endsWith("?");
}

/** Comparison key: trimmed, case-folded, without a leading "Use". */
function chipKey(value: string): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^use\s+/, "");
}

/**
 * The legacy `options` list minus anything the structured chips already
 * cover (by value OR label), so a single question never renders the same
 * choice twice — while any choice that exists ONLY in the legacy list is
 * still offered.
 */
export function legacyChipOptions(
  options: string[] | undefined | null,
  structured: QuestionOption[] | null | undefined
): string[] {
  const covered = new Set(
    (structured ?? [])
      .flatMap((opt) => [opt?.value, opt?.label])
      .filter((value): value is string => typeof value === "string")
      .map(chipKey)
  );
  return (options ?? [])
    .filter(isAnswerOption)
    .filter((option) => !covered.has(chipKey(option)));
}
