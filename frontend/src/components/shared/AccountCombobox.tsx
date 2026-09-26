"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Plus, X } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils/cn";
import type { AccountType } from "@/lib/types/entities";

/**
 * AccountCombobox — accessible searchable account picker (WAI-ARIA 1.2
 * combobox) replacing the raw <select> wherever a GL account is chosen.
 *
 * Account lists grow with every party sub-ledger (1100-0001 …); a native
 * <select> dumps them all with no search.  This keeps the text area
 * WRITABLE (type-to-filter on code or name), groups matches under the five
 * financial-statement sections with their parent head shown, and — when
 * nothing matches — offers "Create account head", an inline form that
 * links the new ledger under the right statement head exactly like the
 * Chart of Accounts page (same columns, same normal-balance rule).
 */

export interface ComboboxAccount {
  id: string;
  code: string;
  name: string;
  account_type?: string | null;
  parent_account_id?: string | null;
}

interface AccountComboboxProps {
  accounts: ComboboxAccount[];
  value: string;
  onChange: (id: string, account: ComboboxAccount | null) => void;
  /** After the inline create flow inserts a ledger, append it to the list. */
  onCreated?: (account: ComboboxAccount) => void;
  organizationId: string;
  /** Must equal the label's htmlFor for screen readers. */
  inputId: string;
  label: string;
  placeholder?: string;
  /** Layout classes from the caller (grid col-spans, widths). */
  className?: string;
  /** Only offer these statement sections (e.g. bills: expense/asset). */
  filterTypes?: AccountType[];
  /** Restrict which statement sections the create flow may pick. */
  createTypes?: AccountType[];
  allowCreate?: boolean;
  /** Adds a "clear / all accounts" row at the top of the list. */
  allowClear?: boolean;
  clearLabel?: string;
}

const SECTIONS: { type: AccountType; label: string }[] = [
  { type: "ASSET", label: "Assets" },
  { type: "LIABILITY", label: "Liabilities" },
  { type: "EQUITY", label: "Equity" },
  { type: "REVENUE", label: "Revenue" },
  { type: "EXPENSE", label: "Expenses" },
];

const TYPE_LABEL: Record<AccountType, string> = {
  ASSET: "Asset",
  LIABILITY: "Liability",
  EQUITY: "Equity",
  REVENUE: "Revenue",
  EXPENSE: "Expense",
};

// DB check constraint (migration 001): normal_balance must match account_type.
const normalBalanceFor = (t: AccountType): "DEBIT" | "CREDIT" =>
  t === "ASSET" || t === "EXPENSE" ? "DEBIT" : "CREDIT";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const sectionIndex = (t?: string | null) => {
  const i = SECTIONS.findIndex((s) => s.type === t);
  return i === -1 ? SECTIONS.length : i;
};

type Row =
  | { kind: "clear" }
  | { kind: "account"; account: ComboboxAccount }
  | { kind: "create" };

export default function AccountCombobox({
  accounts,
  value,
  onChange,
  onCreated,
  organizationId,
  inputId,
  label,
  placeholder = "Search accounts\u2026",
  className,
  filterTypes,
  createTypes,
  allowCreate = true,
  allowClear = false,
  clearLabel = "All accounts",
}: AccountComboboxProps) {
  const selected = useMemo(
    () => accounts.find((a) => a.id === value) ?? null,
    [accounts, value]
  );

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [mode, setMode] = useState<"list" | "create">("list");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    account_type: "EXPENSE" as AccountType,
    parent_account_id: "",
    code: "",
  });

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = `${inputId}-listbox`;

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setMode("list");
    setCreateError(null);
    setActive(0);
  }, []);

  // Close when clicking anywhere outside the combobox.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        close();
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, close]);

  const byId = useMemo(() => {
    const m = new Map<string, ComboboxAccount>();
    for (const a of accounts) m.set(a.id, a);
    return m;
  }, [accounts]);

  /** "under 1100 Accounts Receivable" suffix for child ledgers. */
  const parentSuffix = useCallback(
    (a: ComboboxAccount): string | null => {
      if (!a.parent_account_id) return null;
      const p = byId.get(a.parent_account_id);
      return p ? `under ${p.code} ${p.name}` : null;
    },
    [byId]
  );

  // Filtering: writable text narrows on code or name; scoring ranks
  // exact > prefix > substring, then statement section, then code.
  const filtered = useMemo(() => {
    let base = accounts;
    if (filterTypes?.length) {
      base = base.filter(
        (a) => a.account_type && filterTypes.includes(a.account_type as AccountType)
      );
    }
    const q = query.trim().toLowerCase();
    if (!q) {
      return [...base].sort(
        (x, y) =>
          sectionIndex(x.account_type) - sectionIndex(y.account_type) ||
          x.code.localeCompare(y.code)
      );
    }
    const score = (a: ComboboxAccount) => {
      const c = a.code.toLowerCase();
      const n = a.name.toLowerCase();
      if (c === q || n === q) return 0;
      if (c.startsWith(q) || n.startsWith(q)) return 1;
      if (c.includes(q) || n.includes(q)) return 2;
      return 3;
    };
    return base
      .map((a) => ({ a, s: score(a) }))
      .filter((x) => x.s < 3)
      .sort(
        (x, y) =>
          x.s - y.s ||
          sectionIndex(x.a.account_type) - sectionIndex(y.a.account_type) ||
          x.a.code.localeCompare(y.a.code)
      )
      .map((x) => x.a);
  }, [accounts, filterTypes, query]);

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    if (allowClear) out.push({ kind: "clear" });
    for (const account of filtered) out.push({ kind: "account", account });
    if (allowCreate) out.push({ kind: "create" });
    return out;
  }, [filtered, allowClear, allowCreate]);

  // Code suggestion: children follow the house convention parent-0001…;
  // top-level heads take the statement-series base, skipping used numbers.
  const suggestCode = useCallback(
    (type: AccountType, parentId: string): string => {
      const taken = new Set(accounts.map((a) => a.code));
      const parent = parentId ? byId.get(parentId) : undefined;
      if (parent) {
        const count = accounts.filter(
          (a) => a.parent_account_id === parentId
        ).length;
        for (let n = count + 1; n <= count + 99; n++) {
          const c = `${parent.code}-${String(n).padStart(4, "0")}`;
          if (!taken.has(c)) return c;
        }
      }
      const base: Record<AccountType, number> = {
        ASSET: 1000,
        LIABILITY: 2000,
        EQUITY: 3000,
        REVENUE: 4000,
        EXPENSE: 6000,
      };
      const nums = new Set(
        accounts
          .map((a) => Number.parseInt(a.code, 10))
          .filter((n) => Number.isFinite(n))
      );
      let code = base[type];
      while (nums.has(code) || taken.has(String(code))) code += 100;
      return String(code);
    },
    [accounts, byId]
  );

  const startCreate = useCallback(
    (seed: string) => {
      // Default the statement section from what the user was searching
      // when the matches agree on one section.
      const types = new Set(
        filtered.map((a) => a.account_type).filter(Boolean) as AccountType[]
      );
      const type: AccountType =
        types.size === 1
          ? ([...types][0] as AccountType)
          : (createTypes?.[0] ?? "EXPENSE");
      setForm({
        name: seed.trim(),
        account_type: type,
        parent_account_id: "",
        code: suggestCode(type, ""),
      });
      setCreateError(null);
      setMode("create");
    },
    [filtered, suggestCode, createTypes]
  );

  const handleCreate = async () => {
    const name = form.name.trim();
    const code = form.code.trim();
    if (!name) {
      setCreateError("Name is required");
      return;
    }
    if (!code) {
      setCreateError("Code is required");
      return;
    }
    setCreating(true);
    setCreateError(null);
    const supabase = createClient();
    const { data, error } = await supabase
      .from("accounts")
      .insert({
        organization_id: organizationId,
        code,
        name,
        account_type: form.account_type,
        normal_balance: normalBalanceFor(form.account_type),
        parent_account_id: form.parent_account_id || null,
        description: null,
      })
      .select("id, code, name, account_type, parent_account_id")
      .single();
    setCreating(false);
    if (error || !data) {
      setCreateError(error?.message ?? "Could not create the account");
      return;
    }
    const created = data as ComboboxAccount;
    onCreated?.(created);
    onChange(created.id, created);
    close();
    inputRef.current?.focus();
  };

  const pick = (row: Row) => {
    if (row.kind === "clear") {
      onChange("", null);
      close();
      return;
    }
    if (row.kind === "create") {
      startCreate(query);
      return;
    }
    onChange(row.account.id, row.account);
    close();
  };

  // WAI-ARIA combobox keyboard contract.
  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        setActive(0);
        return;
      }
      if (mode === "list") setActive((i) => Math.min(i + 1, rows.length - 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (mode === "list") setActive((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === "Enter") {
      if (!open) return;
      e.preventDefault();
      if (mode === "create") {
        void handleCreate();
      } else if (rows[active]) {
        pick(rows[active]);
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Tab") close();
  };

  const displayValue = open ? query : selected ? `${selected.code} - ${selected.name}` : "";
  let lastSection = -1;

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <label htmlFor={inputId} className="sr-only">
        {label}
      </label>
      <div className="relative">
        <input
          ref={inputRef}
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && mode === "list" && rows[active]
              ? `${inputId}-row-${active}`
              : undefined
          }
          autoComplete="off"
          className={cn(inputCls, "pr-16")}
          placeholder={selected && !open ? undefined : placeholder}
          value={displayValue}
          onFocus={() => {
            setQuery("");
            setOpen(true);
            setMode("list");
            setActive(0);
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setMode("list");
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {selected && (
            <button
              type="button"
              aria-label={`Clear ${label}`}
              tabIndex={-1}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange("", null);
                inputRef.current?.focus();
              }}
              className="p-1 rounded-md text-text-muted hover:text-error-600 hover:bg-error-50 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "w-4 h-4 text-text-muted transition-transform",
              open && "rotate-180"
            )}
          />
        </div>
      </div>

      <span role="status" aria-live="polite" className="sr-only">
        {open && mode === "list" ? `${filtered.length} accounts match` : ""}
      </span>

      {open && mode === "list" && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={label}
          className="absolute z-40 left-0 right-0 mt-1 max-h-60 overflow-y-auto rounded-xl border border-border-subtle bg-bg-surface shadow-xl py-1 text-sm"
        >
          {rows.length === 0 && (
            <p className="px-3 py-2 text-text-muted">No accounts found</p>
          )}
          {rows.map((row, i) => {
            if (row.kind === "clear") {
              return (
                <div
                  key="clear"
                  id={`${inputId}-row-${i}`}
                  role="option"
                  aria-selected={false}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(row);
                  }}
                  className={cn(
                    "cursor-pointer px-3 py-2 text-text-secondary",
                    active === i && "bg-ai-50 text-ai-700"
                  )}
                >
                  {clearLabel}
                </div>
              );
            }
            if (row.kind === "create") {
              return (
                <div
                  key="create"
                  id={`${inputId}-row-${i}`}
                  role="option"
                  aria-selected={false}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(row);
                  }}
                  className={cn(
                    "cursor-pointer flex items-center gap-2 px-3 py-2 border-t border-border-subtle text-ai-700 font-medium",
                    active === i && "bg-ai-50"
                  )}
                >
                  <Plus className="w-4 h-4 shrink-0" aria-hidden="true" />
                  {query.trim()
                    ? `Create account head "${query.trim()}"`
                    : "Create new account head"}
                </div>
              );
            }

            const a = row.account;
            const sec = sectionIndex(a.account_type);
            const header =
              sec !== lastSection ? (
                <div
                  key={`sec-${sec}`}
                  role="presentation"
                  className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted bg-bg-muted sticky top-0"
                >
                  {SECTIONS[sec]?.label ?? "Other"}
                </div>
              ) : null;
            lastSection = sec;
            const suffix = parentSuffix(a);
            return (
              <Fragment key={a.id}>
                {header}
                <div
                  id={`${inputId}-row-${i}`}
                  role="option"
                  aria-selected={value === a.id}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(row);
                  }}
                  className={cn(
                    "cursor-pointer px-3 py-2 flex items-baseline justify-between gap-3",
                    active === i && "bg-ai-50",
                    value === a.id && "bg-ai-50/60"
                  )}
                >
                  <span className="truncate text-text-primary">
                    <span className="tabular-nums text-text-secondary mr-1.5">
                      {a.code}
                    </span>
                    {a.name}
                  </span>
                  {suffix && (
                    <span className="shrink-0 text-[11px] text-text-muted truncate max-w-[45%]">
                      {suffix}
                    </span>
                  )}
                </div>
              </Fragment>
            );
          })}
        </div>
      )}

      {open && mode === "create" && (
        <div className="absolute z-40 left-0 right-0 mt-1 rounded-xl border border-border-subtle bg-bg-surface shadow-xl p-4 space-y-3">
          <p className="text-xs font-semibold text-text-primary">
            Create account head
          </p>
          <div>
            <label
              htmlFor={`${inputId}-new-name`}
              className="text-xs font-medium text-text-secondary"
            >
              Name *
            </label>
            <input
              id={`${inputId}-new-name`}
              className={`${inputCls} mt-1.5`}
              value={form.name}
              autoFocus
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Office Furniture"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor={`${inputId}-new-type`}
                className="text-xs font-medium text-text-secondary"
              >
                Statement section *
              </label>
              <select
                id={`${inputId}-new-type`}
                className={`${inputCls} mt-1.5`}
                value={form.account_type}
                onChange={(e) => {
                  const t = e.target.value as AccountType;
                  setForm((f) => ({
                    ...f,
                    account_type: t,
                    parent_account_id: "",
                    code: suggestCode(t, ""),
                  }));
                }}
              >
                {SECTIONS.filter(
                  (s) => !createTypes?.length || createTypes.includes(s.type)
                ).map((s) => (
                  <option key={s.type} value={s.type}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor={`${inputId}-new-code`}
                className="text-xs font-medium text-text-secondary"
              >
                Code *
              </label>
              <input
                id={`${inputId}-new-code`}
                className={`${inputCls} mt-1.5`}
                value={form.code}
                onChange={(e) =>
                  setForm((f) => ({ ...f, code: e.target.value }))
                }
              />
            </div>
          </div>
          <div>
            <label
              htmlFor={`${inputId}-new-parent`}
              className="text-xs font-medium text-text-secondary"
            >
              Under head (financial-statement linkage, optional)
            </label>
            <select
              id={`${inputId}-new-parent`}
              className={`${inputCls} mt-1.5`}
              value={form.parent_account_id}
              onChange={(e) => {
                const pid = e.target.value;
                setForm((f) => ({
                  ...f,
                  parent_account_id: pid,
                  code: suggestCode(f.account_type, pid),
                }));
              }}
            >
              <option value="">
                Top level ({TYPE_LABEL[form.account_type]})
              </option>
              {accounts
                .filter(
                  (a) =>
                    a.account_type === form.account_type && a.id !== value
                )
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} - {a.name}
                  </option>
                ))}
            </select>
          </div>
          {createError && (
            <p className="text-xs text-error-600 bg-error-50 rounded-lg px-3 py-2">
              {createError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setMode("list");
                setCreateError(null);
              }}
              className="px-3 py-1.5 rounded-xl text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating}
              className="px-4 py-1.5 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-xs font-medium disabled:opacity-40 transition-colors"
            >
              {creating ? "Creating\u2026" : "Create & select"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}