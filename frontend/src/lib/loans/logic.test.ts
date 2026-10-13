import { describe, expect, it } from "vitest";
import {
  bucketLoans,
  currentNonCurrentSplit,
  num,
  outstandingPrincipal,
  type InstallmentRow,
  type LoanRow,
} from "./logic";

function inst(overrides: Partial<InstallmentRow>): InstallmentRow {
  return {
    installment_no: 1,
    due_date: "2027-06-30",
    opening_principal: 100000,
    principal_component: 50000,
    interest_component: 12000,
    total_due: 62000,
    closing_principal: 50000,
    ...overrides,
  };
}

function loan(overrides: Partial<LoanRow>): LoanRow {
  return {
    id: "l1",
    direction: "BORROWED",
    narration: "Loan - HBL - Vehicle Financing - 2026",
    counterparty: "HBL",
    principal: 1200000,
    status: "ACTIVE",
    ...overrides,
  };
}

describe("currentNonCurrentSplit — derived from the schedule, never manual", () => {
  const schedule: InstallmentRow[] = [
    // two principal installments inside the next 12 months of 2026-10-13
    inst({ installment_no: 1, due_date: "2027-01-15", principal_component: 90000 }),
    inst({ installment_no: 2, due_date: "2027-07-15", principal_component: 95000 }),
    // beyond the horizon
    inst({ installment_no: 3, due_date: "2028-01-15", principal_component: 100000 }),
    inst({ installment_no: 4, due_date: "2028-07-15", principal_component: 105000 }),
    // already paid — excluded entirely
    inst({ installment_no: 0, due_date: "2026-06-30", principal_component: 85000, status: "PAID" }),
  ];

  it("splits principal due within 12 months vs beyond", () => {
    const { current, nonCurrent } = currentNonCurrentSplit(schedule, new Date("2026-10-13"));
    expect(current).toBe(185000);      // 90k + 95k
    expect(nonCurrent).toBe(205000);   // 100k + 105k
    expect(current + nonCurrent).toBe(390000); // paid 85k excluded
  });

  it("keeps overdue unpaid principal in the current portion at a later date", () => {
    const later = currentNonCurrentSplit(schedule, new Date("2027-08-01"));
    // Nothing was paid in this fixture: every unpaid installment is due (or
    // overdue) within the new 12-month horizon, so the whole 390k stays
    // current — past-due principal never silently disappears.
    expect(later.current).toBe(390000);
    expect(later.nonCurrent).toBe(0);
  });

  it("an installment PAID moves out of current portion automatically", () => {
    const afterPayment = schedule.map((r, i) =>
      i === 0 ? { ...r, live_status: "PAID" } : r
    );
    const { current } = currentNonCurrentSplit(afterPayment, new Date("2026-10-13"));
    expect(current).toBe(95000);
  });

  it("handles an empty schedule without throwing", () => {
    expect(currentNonCurrentSplit([], new Date())).toEqual({ current: 0, nonCurrent: 0 });
  });
});

describe("outstandingPrincipal", () => {
  it("is the opening principal of the FIRST unpaid installment", () => {
    const schedule = [
      inst({ status: "PAID", opening_principal: 1000000 }),
      inst({ installment_no: 2, opening_principal: 910000 }),
      inst({ installment_no: 3, opening_principal: 820000 }),
    ];
    expect(outstandingPrincipal(loan({}), schedule)).toBe(910000);
  });
  it("is zero once everything is paid", () => {
    const schedule = [inst({ status: "PAID" })];
    expect(outstandingPrincipal(loan({}), schedule)).toBe(0);
  });
});

describe("bucketLoans + num", () => {
  it("buckets by status, overdue flag and completion", () => {
    const loans = [
      loan({ id: "a", status: "ACTIVE" }),
      loan({ id: "b", status: "ACTIVE", overdue_count: 2 }),
      loan({ id: "c", status: "COMPLETED" }),
    ];
    const b = bucketLoans(loans);
    expect(b.active.map((l) => l.id)).toEqual(["a", "b"]);
    expect(b.overdue.map((l) => l.id)).toEqual(["b"]);
    expect(b.completed.map((l) => l.id)).toEqual(["c"]);
  });
  it("coerces PostgREST numeric strings", () => {
    expect(num("123.45")).toBe(123.45);
    expect(num(null)).toBe(0);
    expect(num("junk")).toBe(0);
  });
});
