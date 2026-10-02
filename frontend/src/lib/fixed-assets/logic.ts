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
  /** The asset-account picker's value ("" = Automatic). */
  asset_account_id?: string | null;
}

/**
 * Client-side mirror of the register's hard refusals — the page shows these
 * BEFORE the round trip instead of letting the 409 surprise the user.
 * Returns the first problem, or null when the submission is acceptable.
 *
 * `accounts` is optional: when the chart is known, an acquisition whose asset
 * account the backend could not resolve is refused here too (same rule the
 * service applies), so the form asks for the account instead of failing.
 */
export function registerBlocker(
  form: RegisterFormValues,
  accounts?: Account[] | null,
  assetAccountId?: string | null
): string | null {
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
  if (accounts && accounts.length > 0) {
    const picked = assetAccountId ?? form.asset_account_id ?? "";
    const accountProblem = assetAccountBlocker(accounts, picked);
    if (accountProblem) return accountProblem;
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
 * Names that make an ASSET account a CURRENT asset (or a control/sub-ledger),
 * never a PPE ledger.  Mirrors the category rules in
 * `database/migrations/039_backfill_account_categories.sql` (BANK, CASH,
 * RECEIVABLE, PREPAID, INVENTORY) plus the tax/control accounts.
 */
const NON_PPE_ASSET_KEYWORDS: readonly string[] = [
  "accumulated depreciation",
  "cash",
  "bank",
  "receivable",
  "payable",
  "prepaid",
  "advance",
  "inventory",
  "stock",
  "vat",
  "tax",
  "drawer",
  "savings",
  "petty",
  "deposit",
];

/** True when the account can be a FIXED-ASSET (PPE) ledger. */
export function isPpeAccount(account: Account): boolean {
  if (account.account_type !== "ASSET") return false;
  // Control accounts (and their sub-ledgers, e.g. the 1100-0001 party rows)
  // are never a PPE heading.
  if (account.is_control_account) return false;
  if (account.parent_account_id) return false;
  const name = (account.name ?? "").toLowerCase();
  return !NON_PPE_ASSET_KEYWORDS.some((k) => name.includes(k));
}

/**
 * The asset-COST picker: PPE ledgers ONLY.
 *
 * Production 2026-10-02 (fixed-assets screenshot): the picker listed every
 * ASSET account — 1010 Bank, 1020 Cash, 1100 Accounts Receivable, the
 * 1100-000x party sub-ledgers, 1300 Prepaid Expenses — so picking an asset
 * account was a minefield.  A PPE acquisition can only ever post to a
 * non-current asset ledger, so the rest is filtered out.
 */
export function ppeAssetAccountOptions(
  accounts: Account[]
): { value: string; label: string }[] {
  return accountOptions(accounts.filter(isPpeAccount), "ASSET");
}

/** The accumulated-depreciation picker: ASSET contra accounts only. */
export function contraAssetAccountOptions(
  accounts: Account[]
): { value: string; label: string }[] {
  return accountOptions(
    accounts.filter(
      (a) =>
        a.account_type === "ASSET" &&
        (a.name ?? "").toLowerCase().includes("accumulated depreciation")
    ),
    "ASSET"
  );
}

/**
 * The depreciation-expense picker: depreciation EXPENSE accounts first; when
 * the chart has none, every expense account (the backend resolves
 * deterministically and refuses only on ambiguity, so hiding the chart would
 * be worse than showing it).
 */
export function depreciationExpenseAccountOptions(
  accounts: Account[]
): { value: string; label: string }[] {
  const depreciation = accounts.filter(
    (a) =>
      a.account_type === "EXPENSE" &&
      (a.name ?? "").toLowerCase().includes("depreciation")
  );
  return accountOptions(
    depreciation.length ? depreciation : accounts,
    "EXPENSE"
  );
}

/** A suggested name for a NEW PPE ledger, from the asset the user typed.
 *
 * ORDER and NAMES mirror the backend's `_ITEM_CATEGORY_RULES`
 * (app/account_resolution.py): a ledger is a CATEGORY, and the name suggested
 * here must be the ledger the BACKEND would open for the same asset — a
 * "Honda Civic" is Vehicles on both sides (production 2026-10-02 created
 * "Other Equipment & Fixtures" for one, because only generic words matched).
 */
export function suggestedAssetAccountName(rawName: string): string {
  const name = (rawName ?? "").trim();
  if (!name) return "Plant & Machinery";
  const lower = name.toLowerCase();
  if (
    /bed|sofa|couch|chair|table|desk|cabinet|shelf|cupboard|wardrobe|furnitur/.test(
      lower
    )
  )
    return "Furniture & Fixtures";
  if (/fitting|fixture|partition|flooring|racking/.test(lower))
    return "Fixtures & Fittings";
  if (
    /laptop|desktop|computer|printer|scanner|monitor|server|router|\bups\b|keyboard|mouse/.test(
      lower
    )
  )
    return "Computer Equipment";
  // Equipment words BEFORE the vehicle makes, so a "Honda generator" stays
  // machinery — never a vehicle.
  if (
    /generator|solar|air conditioner|\bac\b|inverter|boiler|pump|machinery|\bmachine\b|equipment|compressor|cnc|forklift|tractor|\bplant\b/.test(
      lower
    )
  )
    return "Plant & Machinery";
  if (
    /vehicle|automobile|\bcars?\b|\bbikes?\b|motorcycle|scooter|\bvans?\b|\bbuses?\b|\btrucks?\b|lorry|pickup|\bsuv\b|jeep|toyota|honda|suzuki|\bkia\b|hyundai|nissan|mitsubishi|mazda|isuzu|hino|mercedes|benz|\bbmw\b|audi|ford|chevrolet|corolla|civic|hilux|fortuner|prado|sportage|tucson|hiace|cultus|mehran|alto|baleno|picanto|elantra|sonata|accord|prius|vitz|yaris|wagon r|yamaha/.test(
      lower
    )
  )
    return "Vehicles";
  if (
    /building|warehouse|godown|factory|premises|showroom|\bland\b|\bplot\b|real estate/.test(
      lower
    )
  )
    return "Buildings & Land";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** The next free code in a series (e.g. "1500", "1510" -> "1520").
 *
 * Only codes inside the SEED BAND count (seed .. seed+99): a 6100 expense code
 * must never push the next PPE code to 6110.
 */
export function nextAccountCode(
  accounts: Account[],
  seed = "1500",
  step = 10
): string {
  const base = Number(seed);
  const band = accounts
    .map((a) => Number.parseInt(String(a.code ?? ""), 10))
    .filter((n) => Number.isFinite(n) && n >= base && n < base + 100);
  const highest = band.length ? Math.max(...band) : base - step;
  return String(highest + step);
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
 * Mirror of the backend's `_ASSET_ACCOUNT_KEYWORDS`
 * (`app/services/fixed_asset_service.py`): the words the register searches for
 * when the caller does NOT pick an asset account explicitly.  Kept here so the
 * form can show what "Automatic" will actually resolve to — and refuse to
 * promise a match the backend cannot make.
 */
export const ASSET_ACCOUNT_KEYWORDS: readonly string[] = [
  "fixed asset",
  "equipment",
  "computer",
  "machinery",
  "vehicle",
  "furniture",
  "fixture",
];

/** Contra accounts are never the asset-COST account (backend excludes them). */
export const CONTRA_ASSET_KEYWORD = "accumulated depreciation";

/**
 * The account the backend's deterministic resolution would pick for the
 * asset cost: exactly ONE ASSET account whose name contains a keyword and is
 * not a contra account.  Zero or several matches → null (the backend refuses,
 * so the form must ask the user to choose).
 */
export function assetAccountAutoMatch(accounts: Account[]): Account | null {
  const key = CONTRA_ASSET_KEYWORD;
  const matches = accounts.filter((a) => {
    const name = (a.name ?? "").toLowerCase();
    if (a.account_type !== "ASSET") return false;
    if (name.includes(key)) return false;
    return ASSET_ACCOUNT_KEYWORDS.some((k) => name.includes(k));
  });
  return matches.length === 1 ? matches[0] : null;
}

/** The label for the picker's blank/"Automatic" option. */
export function automaticAssetAccountLabel(accounts: Account[]): string {
  const match = assetAccountAutoMatch(accounts);
  return match
    ? `Automatic — ${`${match.code ?? ""} ${match.name}`.trim()}`
    : "Automatic (no unique asset account matches)";
}

/**
 * Why an acquisition with no explicit asset-account pick would be refused —
 * or null when the backend can resolve it by itself.
 */
export function assetAccountBlocker(
  accounts: Account[],
  pickedAccountId?: string | null
): string | null {
  if (pickedAccountId) return null;
  if (assetAccountAutoMatch(accounts)) return null;
  return (
    "No asset account can be resolved automatically: your chart of accounts " +
    "has no single ASSET account whose name matches (fixed asset / equipment / " +
    "computer / machinery / vehicle / furniture / fixture). Choose the asset " +
    "account above, or add one in Chart of Accounts — otherwise the " +
    "acquisition is refused."
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
