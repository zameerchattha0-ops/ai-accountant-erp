import { describe, expect, it } from "vitest";

import {
  accountOptions,
  applyCategoryDefaults,
  depreciationBlocker,
  filterAssets,
  messageOf,
  registerBlocker,
  setupNotices,
  uniqueNameMatch,
  unknownSupplierNotice,
} from "@/lib/fixed-assets/logic";
import type { Account, AssetCategory, FixedAsset } from "@/lib/types/entities";

/** Minimal valid Account — only the fields the helpers read vary per case. */
function acct(
  id: string,
  code: string,
  name: string,
  account_type: Account["account_type"]
): Account {
  return {
    id,
    organization_id: "org-1",
    code,
    name,
    account_type,
    parent_account_id: null,
    normal_balance:
      account_type === "ASSET" || account_type === "EXPENSE" ? "DEBIT" : "CREDIT",
    is_system: false,
    is_control_account: false,
    is_active: true,
    description: null,
  };
}

function asset(overrides: Partial<FixedAsset> = {}): FixedAsset {
  return {
    id: "a1",
    asset_code: "FA-000001",
    name: "Delivery Van",
    purchase_date: "2026-09-01",
    purchase_cost: 4_000_000,
    salvage_value: 0,
    useful_life_years: 5,
    depreciation_method: "STRAIGHT_LINE",
    accumulated_depreciation: 0,
    book_value: 4_000_000,
    status: "ACTIVE",
    ...overrides,
  };
}

const CHART: Account[] = [
  acct("acc-1", "1200", "Machinery", "ASSET"),
  acct("acc-2", "1210", "Accumulated Depreciation", "ASSET"),
  acct("acc-3", "6100", "Depreciation Expense", "EXPENSE"),
  acct("acc-4", "1100", "Bank", "ASSET"),
  acct("acc-5", "5000", "Cost of Sales", "EXPENSE"),
];

describe("messageOf", () => {
  it("surfaces the API's detail verbatim", () => {
    const err = new Error(JSON.stringify({ detail: "Asset name is required." }));
    expect(messageOf(err)).toBe("Asset name is required.");
  });

  it("passes plain-text errors through untouched", () => {
    expect(messageOf(new Error("network down"))).toBe("network down");
    expect(messageOf("boom")).toBe("boom");
  });

  it("keeps non-detail JSON readable", () => {
    expect(messageOf(new Error('{"oops":1}'))).toBe('{"oops":1}');
  });
});

describe("filterAssets", () => {
  const rows = [
    asset(),
    asset({ id: "a2", asset_code: "FA-000002", name: "Old Laptop" }),
    asset({
      id: "a3",
      asset_code: "FA-000003",
      name: "Sold Printer",
      status: "SOLD",
    }),
  ];

  it("narrows by status but keeps everything on ALL", () => {
    expect(filterAssets(rows, "", "ALL")).toHaveLength(3);
    expect(filterAssets(rows, "", "SOLD").map((r) => r.id)).toEqual(["a3"]);
    expect(filterAssets(rows, "", "ACTIVE")).toHaveLength(2);
  });

  it("matches name or asset code, case-insensitively", () => {
    expect(filterAssets(rows, "laptop", "ALL").map((r) => r.id)).toEqual(["a2"]);
    expect(filterAssets(rows, "fa-000003", "ALL").map((r) => r.id)).toEqual([
      "a3",
    ]);
  });

  it("combines search with status", () => {
    expect(filterAssets(rows, "printer", "ACTIVE")).toEqual([]);
    expect(filterAssets(rows, "printer", "SOLD").map((r) => r.id)).toEqual([
      "a3",
    ]);
  });
});

describe("registerBlocker (the 409s the page can prevent)", () => {
  const valid = {
    name: "Delivery Van",
    purchase_cost: "4000000",
    payment_method: "CASH",
    supplier_name: "",
  };

  it("accepts a well-formed registration", () => {
    expect(registerBlocker(valid)).toBeNull();
  });

  it("requires a name", () => {
    expect(registerBlocker({ ...valid, name: " " })).toMatch(/name/i);
    expect(registerBlocker({ ...valid, name: "V" })).toMatch(/name/i);
  });

  it("requires a positive purchase cost", () => {
    expect(registerBlocker({ ...valid, purchase_cost: "" })).toMatch(/cost/i);
    expect(registerBlocker({ ...valid, purchase_cost: "-5" })).toMatch(/cost/i);
    expect(registerBlocker({ ...valid, purchase_cost: "abc" })).toMatch(/cost/i);
  });

  it("requires a supplier on CREDIT (the backend refuses otherwise)", () => {
    expect(registerBlocker({ ...valid, payment_method: "CREDIT" })).toMatch(
      /supplier/i
    );
    expect(
      registerBlocker({
        ...valid,
        payment_method: "CREDIT",
        supplier_name: "Acme Ltd",
      })
    ).toBeNull();
  });
});

describe("setupNotices + uniqueNameMatch (configuration gaps)", () => {
  it("an empty chart reports all three gaps", () => {
    const notices = setupNotices([]);
    expect(notices).toHaveLength(3);
    expect(notices[0]).toMatch(/asset account/i);
    expect(notices.join(" ")).toMatch(/Depreciation Expense/);
    expect(notices.join(" ")).toMatch(/Accumulated Depreciation/);
  });

  it("a complete chart reports nothing", () => {
    expect(setupNotices(CHART)).toEqual([]);
  });

  it("picks exactly one match, never an ambiguous one", () => {
    expect(
      uniqueNameMatch(CHART, "EXPENSE", "depreciation")?.id
    ).toBe("acc-3");
    expect(
      uniqueNameMatch(CHART, "ASSET", "accumulated depreciation")?.id
    ).toBe("acc-2");

    const ambiguous = [
      ...CHART,
      acct("acc-6", "1220", "Accumulated Depreciation - Vehicles", "ASSET"),
    ];
    expect(
      uniqueNameMatch(ambiguous, "ASSET", "accumulated depreciation")
    ).toBeNull();
    expect(uniqueNameMatch(CHART, "LIABILITY", "depreciation")).toBeNull();
  });

  it("an ambiguous Depreciation Expense is reported as a gap", () => {
    const doubled = [
      ...CHART,
      acct("acc-7", "6110", "Depreciation Expense - Vehicles", "EXPENSE"),
    ];
    expect(setupNotices(doubled).join(" ")).toMatch(/Depreciation Expense/);
  });
});

describe("accountOptions", () => {
  it("filters by type and orders by code", () => {
    expect(accountOptions(CHART, "EXPENSE")).toEqual([
      { value: "acc-5", label: "5000 Cost of Sales" },
      { value: "acc-3", label: "6100 Depreciation Expense" },
    ]);
    expect(accountOptions(CHART, "LIABILITY")).toEqual([]);
  });
});

describe("depreciationBlocker (why a charge would be refused)", () => {
  it("is null when the asset carries its accounts", () => {
    expect(
      depreciationBlocker(
        asset({
          gl_depreciation_expense_account_id: "acc-3",
          gl_accumulated_depreciation_account_id: "acc-2",
        }),
        []
      )
    ).toBeNull();
  });

  it("is null when the chart resolves both deterministically", () => {
    expect(depreciationBlocker(asset(), CHART)).toBeNull();
  });

  it("names the missing account(s) when the chart cannot resolve", () => {
    // accumulated exists (unique), depreciation expense does not
    const message = depreciationBlocker(asset(), [
      acct("acc-2", "1210", "Accumulated Depreciation", "ASSET"),
    ]);
    expect(message).toMatch(/would be refused/);
    expect(message).toMatch(/Depreciation Expense/);
    expect(message).not.toMatch(/Accumulated Depreciation \(asset\)/);
  });
});

describe("unknownSupplierNotice (exact-name refusals)", () => {
  const suppliers = [{ name: "Acme Ltd" }];

  it("is silent for an exact match (case-insensitive) or blank input", () => {
    expect(unknownSupplierNotice("acme ltd", suppliers)).toBeNull();
    expect(unknownSupplierNotice("  ", suppliers)).toBeNull();
  });

  it("warns about a name the backend would refuse", () => {
    expect(unknownSupplierNotice("Acme Limited", suppliers)).toMatch(
      /would be refused/
    );
  });
});

describe("applyCategoryDefaults (categories supply the policy)", () => {
  const category: AssetCategory = {
    id: "cat-1",
    name: "Vehicles",
    default_useful_life_years: 5,
    default_depreciation_method: "STRAIGHT_LINE",
  };

  it("fills life and method from the category", () => {
    const next = applyCategoryDefaults(
      { useful_life_years: "", depreciation_method: "REDUCING_BALANCE" },
      category,
      { life: "useful_life_years", method: "depreciation_method" }
    );
    expect(next.useful_life_years).toBe("5");
    expect(next.depreciation_method).toBe("STRAIGHT_LINE");
  });

  it("leaves the draft untouched when no category is chosen", () => {
    const draft = { useful_life_years: "8", depreciation_method: "REDUCING_BALANCE" };
    expect(
      applyCategoryDefaults(draft, null, {
        life: "useful_life_years",
        method: "depreciation_method",
      })
    ).toBe(draft);
  });

  it("keeps the draft life when the category has none", () => {
    const next = applyCategoryDefaults(
      { useful_life_years: "8", depreciation_method: "STRAIGHT_LINE" },
      { ...category, default_useful_life_years: null },
      { life: "useful_life_years", method: "depreciation_method" }
    );
    expect(next.useful_life_years).toBe("8");
  });
});

