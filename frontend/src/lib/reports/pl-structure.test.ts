import { describe, expect, it } from "vitest";
import {
  buildStatement,
  classifyAccount,
  classifyExpenseHead,
  classifyRows,
  classifyRevenueHead,
  COST_OF_SALES,
  headNameFor,
  normalise,
  OPERATING_REVENUE,
  OTHER_INCOME,
  OTHER_OPERATING,
  SECTION_LABELS,
  type PlStatementRow,
} from "./pl-structure";

describe("normalise", () => {
  it("lowercases and strips hyphen/ampersand/underscore differences", () => {
    expect(normalise("Cost of Sales - Goods")).toBe("cost of sales   goods");
    expect(normalise("Office & Administration")).toBe("office and administration");
    expect(normalise("bad_debt")).toBe("bad debt");
    expect(normalise(null)).toBe("");
  });
});

describe("classifyExpenseHead", () => {
  it("sends cost-of-sales heads to COST_OF_SALES (phrases, any separators)", () => {
    expect(classifyExpenseHead("Cost of Sales - Goods")).toBe(COST_OF_SALES);
    expect(classifyExpenseHead("Cost of Goods Sold")).toBe(COST_OF_SALES);
    expect(classifyExpenseHead("COGS")).toBe(COST_OF_SALES);
  });

  it("keeps finance and tax OUT of the operating buckets", () => {
    expect(classifyExpenseHead("Finance Costs")).toBe("finance_costs");
    expect(classifyExpenseHead("Interest Expense")).toBe("finance_costs");
    expect(classifyExpenseHead("Income Tax Expense")).toBe("tax_expense");
    expect(classifyExpenseHead("Tax Expense")).toBe("tax_expense");
  });

  it("maps the operating categories", () => {
    expect(classifyExpenseHead("Selling & Marketing")).toBe("selling_marketing");
    expect(classifyExpenseHead("Marketing & Advertising")).toBe("selling_marketing");
    expect(classifyExpenseHead("Distribution")).toBe("distribution");
    expect(classifyExpenseHead("Office & Administration")).toBe("administrative");
    expect(classifyExpenseHead("Payroll & Staff Costs")).toBe("administrative");
  });

  it("falls unknown/empty custom heads to OTHER_OPERATING (above operating profit)", () => {
    expect(classifyExpenseHead("Mystery Costs")).toBe(OTHER_OPERATING);
    expect(classifyExpenseHead("")).toBe(OTHER_OPERATING);
    expect(classifyExpenseHead(null)).toBe(OTHER_OPERATING);
  });

  it("cost of sales wins over every other phrase (order matters)", () => {
    // "Cost of Sales - Finance Charges" must be CoS, not finance.
    expect(classifyExpenseHead("Cost of Sales - Finance Charges")).toBe(COST_OF_SALES);
  });
});

describe("classifyRevenueHead", () => {
  it("keeps Other Income OUTSIDE operating revenue", () => {
    expect(classifyRevenueHead("Other Income")).toBe(OTHER_INCOME);
    expect(classifyRevenueHead("Other Revenue")).toBe(OTHER_INCOME);
    expect(classifyRevenueHead("Sales Revenue")).toBe(OPERATING_REVENUE);
    expect(classifyRevenueHead("")).toBe(OPERATING_REVENUE);
  });
});

describe("classifyAccount", () => {
  it("uses the HEAD as authority, leaf name only as top-level fallback", () => {
    // A leaf named "Advertising" under "Office & Administration" is
    // administrative, NOT selling — the head wins.
    expect(classifyAccount("EXPENSE", "Office & Administration", "Advertising")).toBe("administrative");
    // Top-level account with no head: its own name is the fallback.
    expect(classifyAccount("EXPENSE", "", "Advertising")).toBe("selling_marketing");
  });

  it("returns null for non P&L account types", () => {
    expect(classifyAccount("ASSET", "Current Assets")).toBeNull();
    expect(classifyAccount("LIABILITY", "Current Liabilities")).toBeNull();
  });
});

describe("headNameFor", () => {
  it("treats a group as its own head, a leaf by its parent, else itself", () => {
    expect(
      headNameFor({ account_type: "EXPENSE", account_code: "6100", account_name: "Payroll", net_amount: 0, is_group: true })
    ).toBe("Payroll");
    expect(
      headNameFor({ account_type: "EXPENSE", account_code: "6110", account_name: "Salaries", net_amount: 0, parent_account_name: "Payroll & Staff Costs" })
    ).toBe("Payroll & Staff Costs");
    expect(
      headNameFor({ account_type: "EXPENSE", account_code: "6000", account_name: "General Operating Expense", net_amount: 0 })
    ).toBe("General Operating Expense");
  });
});

function row(overrides: Partial<PlStatementRow>): PlStatementRow {
  return {
    account_type: "EXPENSE",
    account_code: "0000",
    account_name: "x",
    net_amount: 0,
    ...overrides,
  };
}

describe("classifyRows", () => {
  it("skips group rows and rounding dust; flips revenue sign for display", () => {
    const buckets = classifyRows([
      // Group with a balance — skipped (children carry the postings).
      row({ account_code: "4000", account_name: "Operating Revenue", account_type: "REVENUE", net_amount: -60000, is_group: true }),
      // Leaf revenue: credit-normal (-60000) → +60000 display.
      row({ account_code: "4120", account_name: "Sales Revenue", account_type: "REVENUE", net_amount: -60000, parent_account_name: "Operating Revenue" }),
      // Leaf cost of sales: +40000 stays +40000.
      row({ account_code: "6010", account_name: "Cost of Sales - Goods", net_amount: 40000, parent_account_name: "Cost of Sales" }),
      // Rounding dust — skipped.
      row({ account_code: "6020", account_name: "Freight Inward", net_amount: 0.003, parent_account_name: "Cost of Sales" }),
      // Non-P&L type — skipped.
      row({ account_code: "1000", account_name: "Cash", account_type: "ASSET", net_amount: 5000 }),
    ]);
    expect(buckets.operating_revenue).toHaveLength(1);
    expect(buckets.operating_revenue[0].amount).toBe(60000);
    expect(buckets.cost_of_sales).toHaveLength(1);
    expect(buckets.cost_of_sales[0].amount).toBe(40000);
    // Group did NOT double-count into the bucket.
    expect(buckets.operating_revenue.reduce((s, r) => s + r.amount, 0)).toBe(60000);
  });

  it("classifies a leaf by its section head, not its leaf name", () => {
    const buckets = classifyRows([
      // Leaf says "Advertising" (selling) but hangs under Office & Administration.
      row({ account_code: "6550", account_name: "Advertising", net_amount: 5000, parent_account_name: "Office & Administration" }),
    ]);
    expect(buckets.administrative).toHaveLength(1);
    expect(buckets.selling_marketing).toHaveLength(0);
  });

  it("coerces PostgREST numeric strings", () => {
    const buckets = classifyRows([
      row({ account_code: "6110", account_name: "Salaries", net_amount: "-123.45" as unknown as number, parent_account_name: "Payroll & Staff Costs" }),
    ]);
    expect(buckets.administrative[0].amount).toBe(-123.45);
  });
});

describe("buildStatement — the worked example", () => {
  it("buy 100,000 → sell 60,000 costing 40,000 → Gross Profit 20,000", () => {
    const statement = buildStatement(
      classifyRows([
        row({ account_code: "4120", account_name: "Sales Revenue", account_type: "REVENUE", net_amount: -60000, parent_account_name: "Operating Revenue" }),
        row({ account_code: "6010", account_name: "Cost of Sales - Goods", net_amount: 40000, parent_account_name: "Cost of Sales" }),
      ])
    );
    expect(statement.operating_revenue).toBe(60000);
    expect(statement.cost_of_sales).toBe(40000);
    expect(statement.gross_profit).toBe(20000);
    // The purchase never touched the P&L: no expense row exists for it.
    expect(statement.net_profit).toBe(20000);
    expect(statement.is_loss).toBe(false);
  });

  it("computes Operating Profit, then Other Income / Finance / Tax → Net Profit", () => {
    const statement = buildStatement(
      classifyRows([
        row({ account_code: "4120", account_name: "Sales Revenue", account_type: "REVENUE", net_amount: -100000, parent_account_name: "Operating Revenue" }),
        row({ account_code: "6010", account_name: "Cost of Sales - Goods", net_amount: 60000, parent_account_name: "Cost of Sales" }),
        row({ account_code: "6510", account_name: "Office Supplies", net_amount: 5000, parent_account_name: "Office & Administration" }),
        row({ account_code: "6540", account_name: "Marketing & Advertising", net_amount: 10000, parent_account_name: "Office & Administration" }),
        // Other Income sits OUTSIDE operating revenue.
        row({ account_code: "4910", account_name: "Interest Received", account_type: "REVENUE", net_amount: -3000, parent_account_name: "Other Income" }),
        row({ account_code: "6720", account_name: "Interest Expense", net_amount: 8000, parent_account_name: "Finance Costs" }),
        row({ account_code: "6810", account_name: "Income Tax Expense", net_amount: 4500, parent_account_name: "Tax Expense" }),
      ])
    );
    // 100k - 60k = 40k gross; -15k opex = 25k operating profit.
    expect(statement.gross_profit).toBe(40000);
    expect(statement.operating_expenses.total).toBe(15000);
    expect(statement.operating_profit).toBe(25000);
    // +3k other income −8k finance −4.5k tax = 15.5k net.
    expect(statement.other_income).toBe(3000);
    expect(statement.finance_costs).toBe(8000);
    expect(statement.tax_expense).toBe(4500);
    expect(statement.net_profit).toBe(15500);
    // Other Income is NOT in operating revenue.
    expect(statement.operating_revenue).toBe(100000);
  });

  it("every section carries its human label", () => {
    const statement = buildStatement(classifyRows([]));
    expect(statement.sections.operating_revenue.label).toBe(SECTION_LABELS.operating_revenue);
    expect(statement.sections.cost_of_sales.label).toBe("Cost of Sales");
    expect(statement.operating_expenses.categories.map((c) => c.label)).toEqual([
      "Administrative / General",
      "Selling & Marketing",
      "Distribution",
      "Other Operating Expenses",
    ]);
  });
});

