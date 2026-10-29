import { describe, expect, it } from "vitest";

import { isAnswerOption, legacyChipOptions } from "@/lib/ai/clarification";

/**
 * The account-treatment round sends the SAME choices in `options` AND
 * `question_options[0]`, which rendered every button twice.  These helpers
 * decide what each list contributes.
 */
describe("isAnswerOption", () => {
  it("accepts real choices and rejects questions / blanks", () => {
    expect(isAnswerOption("CASH")).toBe(true);
    expect(isAnswerOption("  Yes, create it  ")).toBe(true);
    expect(isAnswerOption("")).toBe(false);
    expect(isAnswerOption("   ")).toBe(false);
    expect(isAnswerOption("Was this paid in cash?")).toBe(false);
  });
});

describe("legacyChipOptions (no more duplicated buttons)", () => {
  const structured = [
    { value: "CASH", label: "Cash" },
    { value: "CREDIT", label: "On credit" },
  ];

  it("drops choices the structured chips already cover", () => {
    expect(legacyChipOptions(["CASH", "CREDIT"], structured)).toEqual([]);
  });

  it("matches case-insensitively on value OR label", () => {
    expect(legacyChipOptions(["cash", "On Credit"], structured)).toEqual([]);
  });

  it("treats 'Use X' chips as the same choice as 'X'", () => {
    const chips = [{ value: "Vehicles", label: "Use Vehicles" }];
    expect(legacyChipOptions(["Vehicles"], chips)).toEqual([]);
  });

  it("keeps choices that exist ONLY in the legacy list", () => {
    expect(
      legacyChipOptions(["CASH", "Create new account"], structured)
    ).toEqual(["Create new account"]);
  });

  it("still filters question text and blanks out of the legacy list", () => {
    expect(
      legacyChipOptions(["", "What is the transaction amount?", "CASH"], structured)
    ).toEqual([]);
  });

  it("returns the legacy list untouched when there is no structured payload", () => {
    expect(legacyChipOptions(["CASH", "CREDIT"], null)).toEqual([
      "CASH",
      "CREDIT",
    ]);
    expect(legacyChipOptions(["CASH"], [])).toEqual(["CASH"]);
    expect(legacyChipOptions(undefined, structured)).toEqual([]);
  });
});


import { parseEmbeddedSubQuestions } from "@/lib/ai/clarification";

describe("parseEmbeddedSubQuestions", () => {
  it("parses multi-line text into intro, questions and options", () => {
    const raw = `Two things are genuinely missing before I can prepare this quotation:

1. What is the price per bed (or the total quotation amount) in PKR? I have the quantity (2 beds) but no price, and I cannot invent one.

2. FAHAD ASSOCIATES is described as the party you are purchasing FROM (a supplier), but the quotation document in this system is a sales quotation issued to a customer. How should this be recorded?
- (a) It is actually a sales quotation to one of your customers — tell me which customer.
- (b) You want it issued in the name of FAHAD ASSOCIATES as the counterparty anyway (I would need to create a party record for them first).
- (c) You meant a purchase-side document rather than a quotation.

Please answer 1 and 2 and I will proceed.`;

    const result = parseEmbeddedSubQuestions(raw);
    expect(result.questions).toHaveLength(2);
    expect(result.intro).toContain("Two things are genuinely missing");
    expect(result.questions[0].question).toContain("What is the price per bed");
    expect(result.questions[0].options).toBeUndefined();
    expect(result.questions[1].question).toContain("FAHAD ASSOCIATES is described as the party");
    expect(result.questions[1].options).toHaveLength(3);
    expect(result.questions[1].options?.[0].value).toBe("a");
    expect(result.questions[1].options?.[1].value).toBe("b");
    expect(result.questions[1].options?.[2].value).toBe("c");
  });
});
