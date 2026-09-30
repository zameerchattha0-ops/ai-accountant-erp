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
