// Hierarchical P&L classification — pure functions, no I/O.
//
// TypeScript port of app/pl_structure.py (PARITY LAW: keep the two in sync —
// same phrase lists, same order, same section keys, same sign convention).
// The statement is structured around the ACCOUNTING HIERARCHY, never around
// hard-coded account ids: an account is classified by the SECTION HEAD it
// hangs under, so a custom chart with new codes still classifies identically.
//
// SIGN CONVENTION (from get_income_statement RPC): net_amount is
// debit - credit.  Revenue is credit-normal → arrives NEGATIVE and is
// flipped for display; expenses arrive POSITIVE and are shown as deductions.

// ---------------------------------------------------------------------------
// Section keys — the only vocabulary the statement engine speaks.
// ---------------------------------------------------------------------------
export const OPERATING_REVENUE = "operating_revenue";
export const OTHER_INCOME = "other_income";
export const COST_OF_SALES = "cost_of_sales";
export const ADMINISTRATIVE = "administrative";
export const SELLING_MARKETING = "selling_marketing";
export const DISTRIBUTION = "distribution";
export const OTHER_OPERATING = "other_operating";
export const FINANCE_COSTS = "finance_costs";
export const TAX_EXPENSE = "tax_expense";

/** The four operating-expense categories the statement presents separately. */
export const OPERATING_EXPENSE_CATEGORIES = [
  ADMINISTRATIVE,
  SELLING_MARKETING,
  DISTRIBUTION,
  OTHER_OPERATING,
] as const;

/** Human labels, in statement order, for the UI and the agent narrative. */
export const SECTION_LABELS: Record<string, string> = {
  [OPERATING_REVENUE]: "Operating Revenue",
  [OTHER_INCOME]: "Other Income",
  [COST_OF_SALES]: "Cost of Sales",
  [ADMINISTRATIVE]: "Administrative / General",
  [SELLING_MARKETING]: "Selling & Marketing",
  [DISTRIBUTION]: "Distribution",
  [OTHER_OPERATING]: "Other Operating Expenses",
  [FINANCE_COSTS]: "Finance Costs",
  [TAX_EXPENSE]: "Tax Expense",
};

// ---------------------------------------------------------------------------
// Head-name → section matching (mirrors pl_structure.py phrase lists).
// Matching runs against the SECTION HEAD of the account, not the leaf name.
// Phrases are lowercase and hyphen/ampersand-insensitive (see normalise).
// ---------------------------------------------------------------------------

const COST_OF_SALES_PHRASES = ["cost of sales", "cost of goods sold", "cogs"];
const FINANCE_PHRASES = [
  "finance cost",
  "finance charges",
  "interest expense",
  "bank charges",
  "foreign exchange loss",
];
const TAX_PHRASES = ["tax expense", "income tax", "corporate tax", "tax provision"];
const SELLING_PHRASES = ["selling and marketing", "marketing", "advertising", "sales and marketing"];
const DISTRIBUTION_PHRASES = ["distribution", "logistics", "freight out", "shipping and handling"];
const ADMIN_PHRASES = [
  "administrative",
  "administration",
  "office and administration",
  "office expenses",
  "payroll and staff",
  "premises",
  "communication",
  "technology and software",
  "depreciation and amortisation",
  "depreciation and amortization",
];
const OTHER_INCOME_PHRASES = ["other income", "non operating income", "other revenue"];

// Checked in this order — earlier entries win (same order as the Python port).
const ALL_EXPENSE_SECTIONS: ReadonlyArray<readonly [readonly string[], string]> = [
  [COST_OF_SALES_PHRASES, COST_OF_SALES],
  [FINANCE_PHRASES, FINANCE_COSTS],
  [TAX_PHRASES, TAX_EXPENSE],
  [SELLING_PHRASES, SELLING_MARKETING],
  [DISTRIBUTION_PHRASES, DISTRIBUTION],
  [ADMIN_PHRASES, ADMINISTRATIVE],
];

/** Lowercase, hyphen/ampersand-insensitive form used for all matching. */
export function normalise(text: unknown): string {
  if (text === null || text === undefined) return "";
  return String(text).toLowerCase().replace(/&/g, "and").replace(/-/g, " ").replace(/_/g, " ");
}

/**
 * Map an expense section-head name to its statement section.
 *
 * Order is deliberate: cost of sales wins over everything, then finance and
 * tax (NOT operating expenses — they must never land in the administrative
 * bucket), then the operating categories.  Anything unmatched — a custom
 * chart — falls to OTHER_OPERATING so it still sits ABOVE operating profit.
 */
export function classifyExpenseHead(headName: unknown): string {
  const head = normalise(headName);
  if (!head) return OTHER_OPERATING;
  for (const [phrases, section] of ALL_EXPENSE_SECTIONS) {
    for (const phrase of phrases) {
      if (head.includes(phrase)) return section;
    }
  }
  return OTHER_OPERATING;
}

/**
 * Map a revenue section-head name to Operating Revenue or Other Income.
 * Other Income is kept OUTSIDE operating revenue: it does not belong in
 * gross profit or operating profit.
 */
export function classifyRevenueHead(headName: unknown): string {
  const head = normalise(headName);
  if (!head) return OPERATING_REVENUE;
  for (const phrase of OTHER_INCOME_PHRASES) {
    if (head.includes(phrase)) return OTHER_INCOME;
  }
  return OPERATING_REVENUE;
}

/**
 * Classify an account from its type and (head, leaf) names.
 *
 * leafName is a FALLBACK only, used when the account is top-level and
 * therefore its own head — never when a head exists, because a leaf named
 * "Advertising" under "Office & Administration" is administrative, not
 * selling, and the head is the authority.
 */
export function classifyAccount(
  accountType: unknown,
  headName: unknown = "",
  leafName: unknown = ""
): string | null {
  const atype = String(accountType ?? "").toUpperCase();
  if (atype === "REVENUE") return classifyRevenueHead(headName || leafName);
  if (atype === "EXPENSE") return classifyExpenseHead(headName || leafName);
  return null;
}


// ---------------------------------------------------------------------------
// Row classification + statement building
// ---------------------------------------------------------------------------

/** A get_income_statement row (hierarchy columns exist after migration 091). */
export interface PlStatementRow {
  account_type: string;
  account_code: string;
  account_name: string;
  net_amount: number | string;
  parent_account_name?: string | null;
  is_group?: boolean | null;
}

/** A classified presentation row: amount is always sign-normalised. */
export interface BucketRow {
  code: string;
  name: string;
  account_type: string;
  amount: number;
}

export type PlBuckets = Record<string, BucketRow[]>;

/**
 * The section-head name of a row.
 *
 * A GROUP account (is_group) is its own head.  A leaf reports
 * parent_account_name when it has one — that IS its head — and otherwise
 * falls back to its own name.  Deliberately not a recursive walk: the RPC
 * exposes the immediate parent, and head → leaf is the shape the seeded
 * charts use.
 */
export function headNameFor(row: PlStatementRow): string {
  if (row.is_group) return String(row.account_name ?? "");
  const parent = String(row.parent_account_name ?? "");
  if (parent) return parent;
  return String(row.account_name ?? "");
}

function toNumber(value: unknown): number {
  // PostgREST may hand numeric columns back as strings — coerce honestly.
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Bucket income-statement rows into statement sections.
 *
 * GROUP accounts are SKIPPED: their balance double-counts against their
 * children and the leaves carry the postings.  Rows with sub-cent balances
 * are rounding dust and are skipped.  Each returned amount is already
 * sign-normalised for presentation (revenue positive, expenses positive).
 */
export function classifyRows(rows: readonly PlStatementRow[] | null | undefined): PlBuckets {
  const buckets: PlBuckets = {};
  for (const key of Object.keys(SECTION_LABELS)) buckets[key] = [];
  for (const raw of rows ?? []) {
    if (!raw || typeof raw !== "object") continue;
    if (raw.is_group) continue;
    const net = toNumber(raw.net_amount);
    if (Math.abs(net) <= 0.005) continue; // sub-cent rounding dust
    const atype = String(raw.account_type ?? "").toUpperCase();
    const section = classifyAccount(atype, headNameFor(raw));
    if (section === null) continue;
    // Revenue is credit-normal (net_amount negative) → flip for display.
    const amount = atype === "REVENUE" ? -net : net;
    buckets[section].push({
      code: String(raw.account_code ?? ""),
      name: String(raw.account_name ?? ""),
      account_type: atype,
      amount: round2(amount),
    });
  }
  for (const bucket of Object.values(buckets)) {
    bucket.sort((a, b) => a.code.localeCompare(b.code) || a.name.localeCompare(b.name));
  }
  return buckets;
}


export interface SectionGroup {
  label: string;
  rows: BucketRow[];
  total: number;
}

export interface PlStatement {
  operating_revenue: number;
  cost_of_sales: number;
  gross_profit: number;
  operating_expenses: {
    categories: SectionGroup[];
    total: number;
  };
  operating_profit: number;
  other_income: number;
  finance_costs: number;
  tax_expense: number;
  net_profit: number;
  is_loss: boolean;
  sections: Record<string, SectionGroup>;
}

/**
 * Turn classified buckets into the multi-step statement.
 *
 * Every subtotal is computed HERE, from the same buckets the rows come from,
 * so the presentation layer can never show a total that disagrees with the
 * lines above it.
 */
export function buildStatement(buckets: PlBuckets): PlStatement {
  const total = (section: string): number =>
    round2((buckets[section] ?? []).reduce((sum, r) => sum + r.amount, 0));
  const group = (category: string): SectionGroup => ({
    label: SECTION_LABELS[category],
    rows: buckets[category] ?? [],
    total: total(category),
  });

  const operatingRevenue = total(OPERATING_REVENUE);
  const costOfSales = total(COST_OF_SALES);
  const grossProfit = round2(operatingRevenue - costOfSales);

  const opexTotal = round2(
    OPERATING_EXPENSE_CATEGORIES.reduce((sum, c) => sum + total(c), 0)
  );
  const operatingProfit = round2(grossProfit - opexTotal);

  const otherIncome = total(OTHER_INCOME);
  const financeCosts = total(FINANCE_COSTS);
  const taxExpense = total(TAX_EXPENSE);
  const netProfit = round2(operatingProfit + otherIncome - financeCosts - taxExpense);

  return {
    operating_revenue: operatingRevenue,
    cost_of_sales: costOfSales,
    gross_profit: grossProfit,
    operating_expenses: {
      categories: OPERATING_EXPENSE_CATEGORIES.map((c) => group(c)),
      total: opexTotal,
    },
    operating_profit: operatingProfit,
    other_income: otherIncome,
    finance_costs: financeCosts,
    tax_expense: taxExpense,
    net_profit: netProfit,
    is_loss: netProfit < 0,
    sections: {
      [OPERATING_REVENUE]: group(OPERATING_REVENUE),
      [OTHER_INCOME]: group(OTHER_INCOME),
      [COST_OF_SALES]: group(COST_OF_SALES),
      [FINANCE_COSTS]: group(FINANCE_COSTS),
      [TAX_EXPENSE]: group(TAX_EXPENSE),
    },
  };
}

