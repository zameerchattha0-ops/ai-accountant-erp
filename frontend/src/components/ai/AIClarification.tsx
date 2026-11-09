"use client";

import { useState } from "react";
import { MessageCircleQuestion, Send } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { legacyChipOptions, parseEmbeddedSubQuestions, type ParsedQuestionBlock } from "@/lib/ai/clarification";
import type { QuestionOption } from "@/lib/types/api";

interface Props {
  question: string;
  options?: string[];
  /** backend-emitted options per numbered
   *  sub-question (aligned by index; the hardcoded quickOptions
   *  switch below remains the offline fallback). */
  questionOptions?: QuestionOption[][];
  onAnswer: (answer: string) => void;
  /** While a resume request is in flight every control is disabled —
   *  a double click must never fire a duplicate answer. */
  disabled?: boolean;
}

/** Split a consolidated questionnaire ("...:\n1. Q1\n2. Q2") into its
 *  individual questions so EACH gets its own answer box. */
function splitQuestions(question: string): string[] {
  const lines = question.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const numbered = lines
    .map((l) => l.match(/^(\d+)[.)]\s*(.+)$/))
    .filter((m): m is RegExpMatchArray => m !== null);
  const numberedCount = lines.filter((l) => /^\d+[.)]\s/.test(l)).length;
  if (numbered.length >= 2 && numbered.length === numberedCount) {
    return numbered.map((m) => m[2].trim());
  }
  return [];
}

/** the intro is the questionnaire text MINUS the numbered
 *  questions (those render as their own interactive fields - repeating
 *  them verbatim made the card duplicated and cluttered). */
function introText(question: string): string {
  return question
    .split(/\n+/)
    .map((l) => l.trim())
    .filter((l) => l && !/^\d+[.)]\s/.test(l))
    .join("\n");
}

/** strip model markdown (**bold**, backticks,
 *  headings, bullets) before rendering; the backend sanitizes too,
 *  this is the belt-and-braces fallback. */
function sanitizeMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(^|[^*\w])\*(?!\s)([^*]+?)(?<!\s)\*(?!\w)/g, "$1$2")
    .replace(/`/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}[-*]\s+/gm, "");
}

/** tap-to-select answers for known question types
 *  (no typing needed). */
function quickOptions(q: string): string[] | null {
  if (/fixed asset/i.test(q) && /inventory/i.test(q)) {
    return ["a", "b", "c", "d"];
  }
  if (/cash.*(?:or|vs|and|through).*bank|bank.*(?:or|vs|and).*cash/i.test(q)) {
    return ["CASH", "BANK"];
  }
  if (/cash or on credit/i.test(q)) {
    return ["CASH", "BANK", "CREDIT"];
  }
  if (/paid.*(?:now|or).*outstanding|payable/i.test(q)) {
    return ["PAID_NOW", "OUTSTANDING", "PREPAID"];
  }
  return null;
}

/** the
 *  backend payload wins (data-driven), the hardcoded switch is the
 *  fallback.  Dates offer Today/Yesterday chips when the backend did
 *  not send a payload. */
function optionsForSubQuestion(
  q: string,
  index: number,
  questionOptions?: QuestionOption[][],
  parsedQuestions?: ParsedQuestionBlock[]
): QuestionOption[] | null {
  const payload = questionOptions?.[index];
  if (payload && payload.length > 0) {
    return payload;
  }
  const embedded = parsedQuestions?.[index]?.options;
  if (embedded && embedded.length > 0) {
    return embedded;
  }

  // Extract the specific question prompt line (line ending with '?' or the trailing line),
  // preventing informational summaries, employee records, or historical transaction logs above from hijacking options.
  const lines = q.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const questionLine = lines.filter((l) => /\?\s*$/m.test(l)).pop() || lines[lines.length - 1] || q;

  if (
    /how was .*paid|how was .*settled|payment (?:mode|method|type)|how did you pay|cash or (?:credit|bank)|settlement/i.test(
      questionLine
    )
  ) {
    return [
      { value: "CASH", label: "Cash" },
      { value: "BANK", label: "Bank transfer" },
      { value: "CREDIT", label: "On credit" },
    ];
  }
  if (/cash.*(?:or|vs|and|through).*bank|bank.*(?:or|vs|and).*cash/i.test(questionLine)) {
    return [
      { value: "CASH", label: "Cash" },
      { value: "BANK", label: "Bank transfer" },
    ];
  }
  if (/paid.*(?:now|or).*outstanding|payable/i.test(questionLine)) {
    return [
      { value: "PAID_NOW", label: "Paid now" },
      { value: "OUTSTANDING", label: "Payable (pay later)" },
      { value: "PREPAID", label: "Prepaid / advance" },
    ];
  }
  if (/cash or on credit/i.test(questionLine)) {
    return [
      { value: "CASH", label: "Cash" },
      { value: "BANK", label: "Bank" },
      { value: "CREDIT", label: "On credit" },
    ];
  }
  // Date options: ONLY offer Today / Yesterday when the question is genuinely asking the user for a transaction date,
  // NEVER when displaying factual date metadata (e.g. "Date of joining: ...", "transaction date 27 Oct").
  const isFactualDate = /(?:date\s*(?:of|:|\()|\bposted\s+\d|\bjoined\s+on|\brecorded\b)\b/i.test(questionLine) && !/\?\s*$/m.test(questionLine);
  if (
    !isFactualDate &&
    /(?:(?:what|which)\s+(?:is\s+the\s+)?(?:transaction\s+|invoice\s+|payment\s+|expense\s+|bill\s+)?date\b|\bwhen\s+was\s+(?:this|it)\s+(?:paid|received|incurred)\b|\bwhat\s+date\s+did\s+this\s+occur\b)/i.test(
      questionLine
    )
  ) {
    return [
      { value: "TODAY", label: "Today" },
      { value: "YESTERDAY", label: "Yesterday" },
    ];
  }
  if (/what type of account|account type|type of .*in the chart of accounts/i.test(questionLine)) {
    return [
      { value: "Expense", label: "Expense" },
      { value: "Asset", label: "Asset" },
      { value: "Liability", label: "Liability" },
      { value: "Income", label: "Income" },
      { value: "Equity", label: "Equity" },
    ];
  }
  const hardcoded = quickOptions(questionLine);
  if (hardcoded) {
    return hardcoded.map((opt) => ({ value: opt, label: opt }));
  }
  return null;
}

const isPaymentQ = (q: string) => /cash or on credit|how was .*paid|how was .*settled|payment (?:mode|method|type)/i.test(q);
/** R3.3 — the settlement question's Outstanding answer ("c") also
 *  requires the party box (a payable needs a party). */
const isSettlementQ = (q: string) => /paid, or is it outstanding/i.test(q);

export default function AIClarification({
  question,
  options,
  questionOptions,
  onAnswer,
  disabled = false,
}: Props) {
  const parsed = parseEmbeddedSubQuestions(question);
  const hasStructured = parsed.questions.length >= 2;
  const subQuestions = hasStructured
    ? parsed.questions.map((q) => q.question)
    : splitQuestions(question);
  const multi = subQuestions.length >= 2;
  const [custom, setCustom] = useState("");
  // One answer slot per question - answered separately, sent together.
  const [answers, setAnswers] = useState<string[]>(
    multi ? subQuestions.map(() => "") : []
  );
  // the CONDITIONAL party box appears only when CREDIT is
  // selected on the payment question.  Ticking the Local Vendor toggle
  // disables the text box; the typed text is then NOT sent - the standing
  // "Local Vendor" account is used instead.
  const [creditParty, setCreditParty] = useState("");
  const [localVendor, setLocalVendor] = useState(false);
  const paymentIdx = multi
    ? subQuestions.findIndex((q) => isPaymentQ(q))
    : -1;
  const settlementIdx = multi
    ? subQuestions.findIndex((q) => isSettlementQ(q))
    : -1;
  // CREDIT on the payment question — or "Outstanding" (c) on the R3.3
  // settlement question — means a payable, which needs a party.
  const creditSelected =
    (paymentIdx >= 0 &&
      (answers[paymentIdx] ?? "").trim().toUpperCase() === "CREDIT") ||
    (settlementIdx >= 0 &&
      /^(c|3|outstanding|credit)\b/i.test((answers[settlementIdx] ?? "").trim()));
  const allAnswered =
    multi &&
    answers.every((a) => a.trim().length > 0) &&
    (!creditSelected || localVendor || creditParty.trim().length > 0);

  // Quick-response buttons are ONLY for genuine answer options (e.g. "CASH",
  // "CREDIT"). A question (text ending in "?") must never be sent back as an
  // answer - that echoed the question to the backend and caused an infinite
  // clarification loop.  `legacyChipOptions` below applies that same filter.

  // R3.4: structured chips for a SINGLE question (backend payload or
  // fallback).  Typing remains available below the chips.
  const singleOpts = multi
    ? null
    : optionsForSubQuestion(question, 0, questionOptions, parsed.questions);

  // The backend sends the SAME choices in `options` AND `question_options[0]`
  // (agent.py account-treatment round).  The structured chips win and the
  // legacy list only contributes choices they do not already carry - rendering
  // both verbatim duplicated every button.
  const legacyOptions = legacyChipOptions(options, singleOpts);

  const sendMulti = () => {
    if (!allAnswered || disabled) return;
    // Numbered so the backend routes every part to its own question.
    // when CREDIT is selected, the conditional party box
    // is appended as a trailing "N) supplier: X" part (the backend pairs
    // it with the supplier field); the Local Vendor toggle sends the
    // standing "Local Vendor" answer instead of any typed text.
    const lines = subQuestions.map((q, i) => `${i + 1}) ${answers[i].trim()}`);
    if (creditSelected) {
      lines.push(
        `${subQuestions.length + 1}) supplier: ${
          localVendor ? "Local Vendor" : creditParty.trim()
        }`
      );
    }
    onAnswer(lines.join("\n"));
  };

  // Deduplicated header: only the intro prose, never the numbered
  // questions (they render below as their own interactive fields).
  // R3.4a: markdown is stripped before rendering.
  const headerText = sanitizeMarkdown(
    hasStructured
      ? (parsed.intro || "Please provide the following details to proceed:")
      : (multi ? introText(question) : question)
  );

  return (
    <div className="bg-bg-surface rounded-2xl border border-warning-100 shadow-sm p-5 space-y-4">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl bg-warning-50 text-warning-600 shrink-0">
          <MessageCircleQuestion className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-text-primary">I need a bit more info</h3>
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-warning-50 text-warning-600 border border-warning-100">
              AWAITING YOUR ANSWER
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1 whitespace-pre-line">{headerText}</p>
        </div>
      </div>

      {/* R3.4: structured single-question chips (label shown, value sent) */}
      {singleOpts && singleOpts.length > 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {singleOpts.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={disabled}
                onClick={() => onAnswer(opt.value)}
                className="px-4 py-2 rounded-xl bg-bg-muted hover:bg-ai-50 text-xs font-semibold text-text-primary hover:text-ai-700 border border-border-subtle hover:border-ai-200 transition-all shadow-3xs hover:shadow-2xs active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {opt.label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-text-muted">
            Tap an option above or type your answer in the command bar below.
          </p>
        </div>
      )}

      {/* Quick response buttons (legacy `options` list — anything the
          structured chips above do not already offer) */}
      {legacyOptions.length > 0 && !multi && !singleOpts?.length && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {legacyOptions.map((opt) => (
              <button
                key={opt}
                disabled={disabled}
                onClick={() => onAnswer(opt)}
                className="px-4 py-2 rounded-xl bg-bg-muted hover:bg-ai-50 text-xs font-semibold text-text-primary hover:text-ai-700 border border-border-subtle hover:border-ai-200 transition-all shadow-3xs hover:shadow-2xs active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {opt}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-text-muted">
            Tap an option above or type your answer in the command bar below.
          </p>
        </div>
      )}

      {/* ONE ANSWER BOX PER QUESTION - answered separately, sent together */}
      {multi ? (
        <div className="space-y-3">
          {subQuestions.map((q, i) => {
            const opts = optionsForSubQuestion(q, i, questionOptions, parsed.questions);
            const hasSelectedChip = Boolean(answers[i] && opts?.some(o => o.value.toUpperCase() === answers[i]?.toUpperCase()));

            return (
              <div key={i} className="space-y-1.5 p-3 rounded-xl bg-bg-muted/40 border border-border-subtle">
                <label className="text-xs font-medium text-text-primary flex items-start gap-1.5">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-ai-100 text-ai-700 text-[10px] font-semibold shrink-0">
                    {i + 1}
                  </span>
                  <span>{sanitizeMarkdown(q)}</span>
                </label>

                {/* Data-driven chips */}
                {opts && opts.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {opts.map((opt) => {
                      const isSelected = (answers[i] ?? "").toUpperCase() === opt.value.toUpperCase();
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() =>
                            setAnswers((prev) =>
                              prev.map((a, j) => (j === i ? opt.value : a))
                            )
                          }
                          className={cn(
                            "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all",
                            isSelected
                              ? "bg-ai-500 text-white border-ai-600 shadow-2xs"
                              : "bg-bg-surface text-text-secondary border-border-default hover:border-ai-200"
                          )}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Only render text input if no chips exist OR if user wants to type custom value */}
                {(!opts || opts.length === 0 || !hasSelectedChip) && (
                  <input
                    type="text"
                    value={answers[i] ?? ""}
                    autoFocus={i === 0 && !opts}
                    disabled={disabled}
                    onChange={(e) =>
                      setAnswers((prev) =>
                        prev.map((a, j) => (j === i ? e.target.value : a))
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && allAnswered) sendMulti();
                    }}
                    placeholder={opts ? "Or type a custom answer..." : "Type your answer here..."}
                    className="w-full px-3 py-1.5 rounded-lg border border-border-default bg-bg-surface text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-ai-500 transition"
                  />
                )}

                {/* Conditional party box for credit ledger */}
                {(i === paymentIdx || i === settlementIdx) && creditSelected && (
                  <div className="space-y-2 rounded-xl border border-ai-200 bg-ai-50/50 p-2.5 mt-2">
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={localVendor}
                        onChange={(e) => setLocalVendor(e.target.checked)}
                        className="w-4 h-4 rounded border-border-default text-ai-600 focus:ring-ai-500/30"
                      />
                      <span className="text-[11px] font-medium text-text-secondary">
                        Purchased from a local vendor (one-off - no party name needed)
                      </span>
                    </label>
                    <input
                      type="text"
                      value={creditParty}
                      disabled={localVendor}
                      onChange={(e) => setCreditParty(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && allAnswered) sendMulti();
                      }}
                      placeholder="Party / vendor name for the credit ledger..."
                      className="w-full px-3 py-1.5 rounded-lg border border-border-default bg-bg-surface text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-ai-500 transition disabled:bg-bg-muted disabled:text-text-muted"
                    />
                  </div>
                )}
              </div>
            );
          })}

          <div className="flex justify-end pt-1">
            <button
              onClick={sendMulti}
              disabled={!allAnswered || disabled}
              className="btn-3d px-4 py-2 rounded-xl bg-ai-500 text-white hover:bg-ai-600 transition flex items-center gap-1.5 text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-2xs"
            >
              <Send className="w-3.5 h-3.5" />
              Submit Answers
            </button>
          </div>
        </div>
      ) : (
        /* Single question without predefined chips */
        !singleOpts?.length && !legacyOptions.length && (
          <div className="space-y-1.5">
            <div className="flex gap-2">
              <input
                type="text"
                value={custom}
                autoFocus
                disabled={disabled}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && custom.trim() && !disabled) {
                    onAnswer(custom.trim());
                    setCustom("");
                  }
                }}
                placeholder="Type your answer here..."
                className="flex-1 px-3 py-2 rounded-xl border border-border-default bg-bg-surface text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-ai-500 transition"
              />
              <button
                onClick={() => {
                  if (custom.trim() && !disabled) {
                    onAnswer(custom.trim());
                    setCustom("");
                  }
                }}
                disabled={!custom.trim() || disabled}
                className="btn-3d px-3 py-2 rounded-xl bg-ai-500 text-white hover:bg-ai-600 transition flex items-center gap-1.5 text-xs font-semibold disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                Submit
              </button>
            </div>
          </div>
        )
      )}
    </div>
  );
}

