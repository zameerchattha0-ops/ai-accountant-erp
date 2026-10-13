// Loans & Financing — pure logic (mirror of app/services/loan_service.py
// schedule math; PARITY LAW: keep the two in sync).  The schedule is the
// source of truth: outstanding, current/non-current portions and status
// buckets are all DERIVED, never manually maintained.

export type LoanDirection = "BORROWED" | "GIVEN";
export type LoanFrequency = "MONTHLY" | "QUARTERLY" | "SEMI_ANNUAL" | "ANNUALLY" | "CUSTOM";

export interface LoanRow {
  id: string;
  direction: LoanDirection;
  narration: string;
  counterparty: string;
  purpose?: string | null;
  principal: number | string;
  currency_code?: string;
  loan_date?: string;
  interest_rate?: number | string;
  interest_method?: string;
  tenure_months?: number;
  frequency?: LoanFrequency;
  first_payment_date?: string;
  maturity_date?: string | null;
  status: string;
  current_portion?: number | string;
  noncurrent_portion?: number | string;
  principal_paid?: number | string;
  next_due_date?: string | null;
  overdue_count?: number | string;
  total_interest?: number | string;
}

export interface InstallmentRow {
  installment_no: number;
  due_date: string;
  opening_principal: number | string;
  principal_component: number | string;
  interest_component: number | string;
  total_due: number | string;
  closing_principal: number | string;
  live_status?: string;
  status?: string;
}

export function num(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/** Total outstanding principal = principal still owed on the schedule. */
export function outstandingPrincipal(loan: LoanRow, schedule: InstallmentRow[]): number {
  const unpaid = schedule.filter(
    (r) => !["PAID", "WAIVED"].includes(String(r.live_status ?? r.status ?? ""))
  );
  if (unpaid.length === 0) return 0;
  return round2(num(unpaid[0].opening_principal));
}

/**
 * Current vs non-current split AT A REPORTING DATE — derived from the
 * schedule: principal due within the next 12 months is the current portion;
 * everything beyond is non-current.  Recomputes on every call, so an paid
 * installment, a date change or a restructure updates it automatically.
 */
export function currentNonCurrentSplit(
  schedule: InstallmentRow[],
  asOf: Date = new Date()
): { current: number; nonCurrent: number } {
  const horizon = new Date(asOf);
  horizon.setFullYear(horizon.getFullYear() + 1);
  let current = 0;
  let remaining = 0;
  for (const row of schedule) {
    if (["PAID", "WAIVED"].includes(String(row.live_status ?? row.status ?? ""))) continue;
    const principal = num(row.principal_component);
    if (new Date(row.due_date) <= horizon) current += principal;
    else remaining += principal;
  }
  return { current: round2(current), nonCurrent: round2(remaining) };
}

/** Status buckets for the page tabs. */
export function bucketLoans(loans: LoanRow[]): {
  active: LoanRow[];
  upcoming: LoanRow[];
  overdue: LoanRow[];
  completed: LoanRow[];
} {
  return {
    active: loans.filter((l) => l.status === "ACTIVE"),
    upcoming: loans.filter((l) => l.status === "ACTIVE" && num(l.next_due_date ? 1 : 0) > 0),
    overdue: loans.filter((l) => l.status === "ACTIVE" && num(l.overdue_count) > 0),
    completed: loans.filter((l) => l.status === "COMPLETED"),
  };
}

export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
