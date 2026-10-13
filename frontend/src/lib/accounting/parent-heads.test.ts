import { describe, expect, it } from "vitest";
import {
  allowedParentHeads,
  EXPENSE_PARENT_HEADS,
  isAllowedParentName,
  PARENT_HEADS_BY_TYPE,
} from "./parent-heads";

describe("allowedParentHeads", () => {
  it("returns the context-sensitive heads per account type", () => {
    expect(allowedParentHeads("ASSET")).toEqual(["Current Assets", "Non-Current Assets"]);
    expect(allowedParentHeads("LIABILITY")).toEqual(["Current Liabilities", "Non-Current Liabilities"]);
    expect(allowedParentHeads("EXPENSE")).toEqual(EXPENSE_PARENT_HEADS);
    expect(allowedParentHeads("REVENUE")).toEqual(["Operating Revenue", "Other Income"]);
    expect(allowedParentHeads("EQUITY")).toEqual(["Equity"]);
  });

  it("is case/space insensitive and returns [] for unknown types (no parent invented)", () => {
    expect(allowedParentHeads("expense")).toBe(PARENT_HEADS_BY_TYPE.EXPENSE);
    expect(allowedParentHeads("  Asset ")).toBe(PARENT_HEADS_BY_TYPE.ASSET);
    expect(allowedParentHeads("SUSPENSE")).toEqual([]);
    expect(allowedParentHeads(null)).toEqual([]);
    expect(allowedParentHeads(undefined)).toEqual([]);
  });
});

describe("isAllowedParentName", () => {
  it("accepts exact head names case-insensitively", () => {
    expect(isAllowedParentName("EXPENSE", "Cost of Sales")).toBe(true);
    expect(isAllowedParentName("EXPENSE", "cost of sales")).toBe(true);
    expect(isAllowedParentName("EXPENSE", "  Tax Expense  ")).toBe(true);
    expect(isAllowedParentName("REVENUE", "Other Income")).toBe(true);
  });

  it("rejects cross-type parents, partial matches and empty names", () => {
    // Revenue head is not an expense head.
    expect(isAllowedParentName("EXPENSE", "Other Income")).toBe(false);
    // Same words but not an exact head.
    expect(isAllowedParentName("EXPENSE", "Cost of Sales - Goods")).toBe(false);
    // A leaf name, not a head.
    expect(isAllowedParentName("EXPENSE", "Advertising")).toBe(false);
    // Cross-type check: asset head never valid for an expense account.
    expect(isAllowedParentName("EXPENSE", "Current Assets")).toBe(false);
    expect(isAllowedParentName("EXPENSE", "")).toBe(false);
    expect(isAllowedParentName("EXPENSE", null)).toBe(false);
    // Unknown type → nothing allowed.
    expect(isAllowedParentName("MYSTERY", "Cost of Sales")).toBe(false);
  });
});
