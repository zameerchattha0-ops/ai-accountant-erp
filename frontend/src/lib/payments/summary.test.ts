import { describe, expect, it } from "vitest";
import { SCAN_MAX_ROWS, summarizeRows } from "./summary";

describe("summarizeRows", () => {
  it("sums completed non-transfer payments as paid, pending separately", () => {
    const rows = [
      { status: "COMPLETED", amount: 100, is_transfer: false },
      { status: "COMPLETED", amount: 50, is_transfer: true },
      { status: "PENDING", amount: 25 },
      { status: "CANCELLED", amount: 999 },
      { status: "REVERSED", amount: 77 },
    ];
    const s = summarizeRows(rows);
    expect(s).toEqual({ paid: 100, pending: 25, count: 5 });
  });

  it("includes transfers in the paid figure when asked (receipts)", () => {
    const rows = [
      { status: "COMPLETED", amount: 50, is_transfer: true },
      { status: "COMPLETED", amount: 10 },
    ];
    expect(summarizeRows(rows, { countTransfersInPaid: true }).paid).toBe(60);
    expect(summarizeRows(rows).paid).toBe(10);
  });

  it("coerces string amounts (numeric columns arrive as strings from PostgREST)", () => {
    const s = summarizeRows([
      { status: "COMPLETED", amount: "12.50", is_transfer: false },
      { status: "PENDING", amount: "0.50" },
    ]);
    expect(s.paid).toBeCloseTo(12.5);
    expect(s.pending).toBeCloseTo(0.5);
  });

  it("never produces NaN from junk amounts", () => {
    const s = summarizeRows([
      { status: "COMPLETED", amount: "not-a-number", is_transfer: false },
      { status: "PENDING", amount: null as unknown as number },
    ]);
    expect(Number.isNaN(s.paid)).toBe(false);
    expect(Number.isNaN(s.pending)).toBe(false);
  });

  it("returns zeroes for an empty list", () => {
    expect(summarizeRows([])).toEqual({ paid: 0, pending: 0, count: 0 });
  });
});

describe("scan bounds", () => {
  it("caps the fallback scan far below unbounded territory", () => {
    expect(SCAN_MAX_ROWS).toBe(100_000);
  });
});
