import type { Account, AssetCategory, FixedAsset } from "@/lib/types/entities";

/**
 * Pure decision helpers for the Fixed Assets page.
 *
 * Everything the page DERIVES (filters, validation, picker options, and the
 * preflight explanation of a would-be 409) lives here as plain functions so a
 * test can pin the behaviour without mounting React.
 */

/** The API carries the refusal text in ``detail`` — surface it verbatim. */
export function messageOf(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* plain-text error — already readable */
  }
  return raw;
}

/** Search (name/code) + status filter over the register rows. */
export function filterAssets(
  items: FixedAsset[],
  search: string,
  status: string
): FixedAsset[] {
  const q = search.trim().toLowerCase();
  return items.filter((row) => {
    if (status !== "ALL" && row.status !== status) return false;
    if (!q) return true;
    return (
      row.name.toLowerCase().includes(q) ||
      (row.asset_code ?? "").toLowerCase().includes(q)
    );
  });
}

export interface RegisterFormValues {
  name: string;
  purchase_cost: string;
  payment_method: string;
  supplier_name: string;
}

/**
 * Client-side mirror of the register's hard refusals — the page shows these
 * BEFORE the round trip instead of letting the 409 surprise the user.
 * Returns the first problem, or null when the submission is acceptable.
 */
export function registerBlocker(form: RegisterFormValues): string | null {
  if (form.name.trim().length < 2) return "An asset name is required.";
  const cost = Number(form.purchase_cost);
  if (!form.purchase_cost.trim() || !Number.isFinite(cost) || cost <= 0) {
    return "A positive purchase cost is required.";
  }
  if (
    form.payment_method === "CREDIT" &&
    !form.supplier_name.trim()
  ) {
    return (
      "A credit acquisition needs a supplier — Accounts Payable can only be " +
      "credited against one. Pick a supplier or choose another payment method."
    );
  }
  return null;
}

/**
 * Configuration gaps the register would hit (the honest explanation of a 409
 * BEFORE it happens): what the chart of accounts is missing.
 */
export function setupNotices(accounts: Account[]): string[] {
  const notices: string[] = [];
  if (!accounts.some((a) => a.account_type === "ASSET")) {
    notices.push(
      "Your chart of accounts has no asset account, so an acquisition cannot " +
        "be capitalised. Create one (e.g. 'Machinery' or 'Computer Equipment') " +
        "in Chart of Accounts first."
    );
  }
  if (!uniqueNameMatch(accounts, "EXPENSE", "depreciation")) {
    notices.push(
      "No unique 'Depreciation Expense' (expense) account — depreciation " +
        "charges will be refused until exactly one exists."
    );
  }
  if (!uniqueNameMatch(accounts, "ASSET", "accumulated depreciation")) {
    notices.push(
      "No unique 'Accumulated Depreciation' (asset) account — depreciation " +
        "charges will be refused until exactly one exists."
    );
  }
  return notices;
}

/**
 * The deterministic account the backend would choose: exactly ONE account of
 * the type whose name contains ``keyword`` (zero or ambiguous → null, and the
 * caller must pick explicitly). Mirrors ``_resolve_gl_account``.
 */
export function uniqueNameMatch(
  accounts: Account[],
  accountType: string,
  keyword: string
): Account | null {
  const key = keyword.toLowerCase();
  const matches = accounts.filter(
    (a) =>
      a.account_type === accountType &&
      (a.name ?? "").toLowerCase().includes(key)
  );
  return matches.length === 1 ? matches[0] : null;
}

/** Picker options for one account type, in chart order. */
export function accountOptions(
  accounts: Account[],
  accountType: string
): { value: string; label: string }[] {
  return accounts
    .filter((a) => a.account_type === accountType)
    .sort((a, b) => String(a.code ?? "").localeCompare(String(b.code ?? "")))
    .map((a) => ({ value: a.id, label: `${a.code ?? ""} ${a.name}`.trim() }));
}

/**
 * Preflight for one depreciation charge: null when it CAN post (an explicit
 * account on the asset/form, or a unique chart match), otherwise the missing
 * pieces — so the modal can offer the pickers instead of a raw 409.
 */
export function depreciationBlocker(
  asset: FixedAsset,
  accounts: Account[]
): string | null {
  const missing: string[] = [];
  const expenseOk =
    Boolean(asset.gl_depreciation_expense_account_id) ||
    Boolean(uniqueNameMatch(accounts, "EXPENSE", "depreciation"));
  const accumulatedOk =
    Boolean(asset.gl_accumulated_depreciation_account_id) ||
    Boolean(uniqueNameMatch(accounts, "ASSET", "accumulated depreciation"));
  if (!expenseOk) missing.push("Depreciation Expense (expense)");
  if (!accumulatedOk) missing.push("Accumulated Depreciation (asset)");
  if (!missing.length) return null;
  return (
    `This charge would be refused: the chart of accounts has no unique ` +
    `${missing.join(" and ")} account. Pick the accounts below, or add them ` +
    `in Chart of Accounts.`
  );
}

/**
 * A supplier name the register would refuse: the backend only accepts an
 * EXACT name match, so warn before the round trip (409 on a near miss).
 * Returns null when blank or found.
 */
export function unknownSupplierNotice(
  supplierName: string,
  suppliers: { name: string }[]
): string | null {
  const name = supplierName.trim().toLowerCase();
  if (!name) return null;
  if (suppliers.some((s) => (s.name ?? "").trim().toLowerCase() === name)) {
    return null;
  }
  return (
    `No supplier named "${supplierName.trim()}" exists yet — an acquisition ` +
      `with that name would be refused. Add it in Suppliers (or fix the ` +
      `spelling) first.`
  );
}

/**
 * Apply a category's policy to a draft form — the category supplies life and
 * method (and its GL accounts) so the register never invents them.
 */
export function applyCategoryDefaults<T extends object>(
  form: T,
  category: AssetCategory | null,
  accountFields: { life: keyof T; method: keyof T }
): T {
  if (!category) return form;
  return {
    ...form,
    [accountFields.life]:
      category.default_useful_life_years != null
        ? String(category.default_useful_life_years)
        : form[accountFields.life],
    [accountFields.method]:
      category.default_depreciation_method || form[accountFields.method],
  } as T;
}
