// Context-sensitive parent-account heads — TypeScript port of
// allowed_parent_heads / PARENT_HEADS_BY_TYPE in app/account_resolution.py
// (PARITY LAW: keep the two in sync).
//
// The Parent Account field is context-sensitive: depending on the account
// TYPE being created, only the section heads of that type may be offered —
// never a cross-type parent (an expense under Accounts Receivable) and never
// an invented name.  Matching is name-based and case-insensitive on the
// seeded chart's headings, so a chart seeded with different codes still
// validates.  An unknown type returns [] — no parent is invented (a
// top-level account is the honest fallback).

export const ASSET_PARENT_HEADS = ["Current Assets", "Non-Current Assets"] as const;
export const LIABILITY_PARENT_HEADS = ["Current Liabilities", "Non-Current Liabilities"] as const;
export const EQUITY_PARENT_HEADS = ["Equity"] as const;
export const EXPENSE_PARENT_HEADS = [
  "Cost of Sales",
  "Operating Expenses",
  "Finance Costs",
  "Tax Expense",
  "Other Expenses",
] as const;
export const REVENUE_PARENT_HEADS = ["Operating Revenue", "Other Income"] as const;

export const PARENT_HEADS_BY_TYPE: Record<string, readonly string[]> = {
  ASSET: ASSET_PARENT_HEADS,
  LIABILITY: LIABILITY_PARENT_HEADS,
  EQUITY: EQUITY_PARENT_HEADS,
  EXPENSE: EXPENSE_PARENT_HEADS,
  REVENUE: REVENUE_PARENT_HEADS,
};

/** The section heads a NEW account of *accountType* may be parented under. */
export function allowedParentHeads(accountType: unknown): readonly string[] {
  const key = String(accountType ?? "").trim().toUpperCase();
  return PARENT_HEADS_BY_TYPE[key] ?? [];
}

/** May an account of *accountType* be parented under *parentName*? */
export function isAllowedParentName(accountType: unknown, parentName: unknown): boolean {
  const heads = allowedParentHeads(accountType);
  if (heads.length === 0) return false;
  const candidate = String(parentName ?? "").trim().toLowerCase();
  if (!candidate) return false;
  return heads.some((h) => h.trim().toLowerCase() === candidate);
}
