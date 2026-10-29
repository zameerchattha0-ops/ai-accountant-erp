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


export interface ParsedQuestionBlock {
  id: number;
  question: string;
  options?: QuestionOption[];
}

export interface ParsedQuestionnaire {
  intro: string;
  questions: ParsedQuestionBlock[];
}

/**
 * Robustly parses multi-line question text emitted by LLMs into structured questions
 * with isolated intros, clean questions, and extracted sub-options ((a), (b), (c))
 * so each question renders its own interactive answer box and clickable chips.
 */
export function parseEmbeddedSubQuestions(rawText: string): ParsedQuestionnaire {
  const text = (rawText || "").trim();
  if (!text) {
    return { intro: "", questions: [] };
  }

  const numberRegex = /(?:^|\n)\s*(\d+)[.)]\s*/g;
  const matches: Array<{ num: number; index: number; end: number }> = [];
  let m: RegExpExecArray | null;

  while ((m = numberRegex.exec(text)) !== null) {
    matches.push({
      num: parseInt(m[1], 10),
      index: m.index,
      end: m.index + m[0].length,
    });
  }

  if (matches.length >= 2) {
    const firstMatch = matches[0];
    const rawIntro = text.slice(0, firstMatch.index).trim();
    const questions: ParsedQuestionBlock[] = [];

    for (let i = 0; i < matches.length; i++) {
      const current = matches[i];
      const next = matches[i + 1];
      const block = text.slice(current.end, next ? next.index : undefined).trim();

      const optRegex = /(?:^|\n)\s*[-*•]?\s*\(?([a-zA-Z0-9])\)?[.)]\s*(.+)/g;
      const opts: QuestionOption[] = [];
      let firstOptIdx = -1;
      let om: RegExpExecArray | null;

      while ((om = optRegex.exec(block)) !== null) {
        if (firstOptIdx === -1) {
          firstOptIdx = om.index;
        }
        const val = om[1].trim();
        const desc = om[2].trim();
        opts.push({
          value: val,
          label: desc.startsWith("(") ? desc : `(${val}) ${desc}`,
        });
      }

      let qText = firstOptIdx >= 0 ? block.slice(0, firstOptIdx).trim() : block;
      qText = qText.replace(/(?:^|\n)\s*(?:please answer|let me know|reply with).+$/i, "").trim();

      questions.push({
        id: current.num,
        question: qText,
        options: opts.length > 0 ? opts : undefined,
      });
    }

    return { intro: rawIntro, questions };
  }

  return { intro: text, questions: [] };
}
