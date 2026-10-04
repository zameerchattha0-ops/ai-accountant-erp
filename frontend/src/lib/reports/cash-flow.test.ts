import { describe, expect, it } from "vitest";
import {
  CHUNK_SIZE,
  EMPTY_TOTALS,
  MAX_ROWS,
  computeCategoryTotals,
  netOf,
} from "./cash-flow";

describe("computeCategoryTotals", () => {
  it("sums net_amount per category, coercing PostgREST numeric strings", () => {
    const totals = computeCategoryTotals([
      { cash_flow_category: "OPERATING", net_amount: "100.50" },
      { cash_flow_category: "OPERATING", net_amount: 50 },
      { cash_flow_category: "INVESTING", net_amount: -20 },
      { cash_flow_category: "FINANCING", net_amount: "5" },
    ]);
    expect(totals.OPERATING).toBeCloseTo(150.5);
    expect(totals.INVESTING).toBe(-20);
    expect(totals.FINANCING).toBe(5);
  });

  it("ignores unknown categories and junk values", () => {
    const totals = computeCategoryTotals([
      { cash_flow_category: "MYSTERY", net_amount: 999 },
      { cash_flow_category: "OPERATING", net_amount: "not-a-number" },
    ]);
    expect(totals).toEqual(EMPTY_TOTALS);
  });

  it("returns zeroed totals for an empty list", () => {
    expect(computeCategoryTotals([])).toEqual(EMPTY_TOTALS);
  });
});

describe("netOf", () => {
  it("adds the three categories", () => {
    expect(
      netOf({ OPERATING: 10, INVESTING: -3, FINANCING: 2 })
    ).toBe(9);
  });
});

describe("fetch bounds", () => {
  it("chunks below the PostgREST response cap and hard-caps the statement", () => {
    expect(CHUNK_SIZE).toBe(1000);
    expect(MAX_ROWS).toBe(20_000);
    expect(MAX_ROWS % CHUNK_SIZE).toBe(0);
  });
});
