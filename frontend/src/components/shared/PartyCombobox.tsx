"use client";

/**
 * PartyCombobox — searchable, server-backed picker for customers/suppliers.
 *
 * Replaces the native `<select>` that used to render the ENTIRE parties table
 * as options (§7/§54). Behaviour:
 *
 * - opens instantly on a bounded "recently added" page (20 rows) + the parties
 *   this user picked during the session ("Recent");
 * - typing debounces (~200 ms) into ONE server search across
 *   name / code / email / phone, and superseded responses are cancelled;
 * - the list viewport is constrained (max-h-64) and scrolls INSIDE the
 *   dropdown — it never pushes the page or the modal around;
 * - full keyboard model (up / down / Enter / Esc), WAI-ARIA combobox semantics;
 * - "+ Create new …" lives at the bottom of the dropdown (§22): the user
 *   creates the party and lands back on the same form with it selected;
 * - selected labels resolve even for archived parties (history keeps them).
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils/cn";
import { professionalName } from "@/lib/utils/displayName";
import {
  createRecentList,
  createSequencer,
  ilikeAny,
} from "@/lib/lists/logic";

export interface PartyOption {
  id: string;
  name: string;
  code?: string | null;
}

export type PartyKind = "customer" | "supplier";

interface PartyComboboxProps {
  kind: PartyKind;
  organizationId: string;
  value: string;
  onChange: (id: string, party: PartyOption | null) => void;
  /** Must match the label's htmlFor for screen readers. */
  inputId: string;
  /** Used for aria-label when the page renders its own <label>. */
  label: string;
  placeholder?: string;
  /** Layout classes from the caller (grid col-spans, widths). */
  className?: string;
  allowCreate?: boolean;
  /** Sent as currency_code on inline create (org base currency). */
  baseCurrency?: string;
  onCreated?: (party: PartyOption) => void;
  disabled?: boolean;
}

const TABLES: Record<
  PartyKind,
  { table: string; codeCol: string; noun: string }
> = {
  customer: { table: "customers", codeCol: "customer_code", noun: "Customer" },
  supplier: { table: "suppliers", codeCol: "supplier_code", noun: "Supplier" },
};

const OPTIONS_LIMIT = 20;

/* Session-scoped caches: labels for ids we have already seen (so a selected
   archived party still renders) and the user's recent picks per org+table. */
const labelCache = new Map<string, PartyOption>();
const recentCache = new Map<string, ReturnType<typeof createRecentList>>();

const recentListFor = (table: string, orgId: string) => {
  const key = `${table}:${orgId}`;
  let list = recentCache.get(key);
  if (!list) {
    list = createRecentList(5);
    recentCache.set(key, list);
  }
  return list;
};

type Mode = "list" | "create";

export default function PartyCombobox({
  kind,
  organizationId,
  value,
  onChange,
  inputId,
  label,
  placeholder,
  className,
  allowCreate = true,
  baseCurrency,
  onCreated,
  disabled = false,
}: PartyComboboxProps) {
  const { table, codeCol, noun } = TABLES[kind];
  const selectCols = `id,name,${codeCol}`;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<PartyOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [mode, setMode] = useState<Mode>("list");
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PartyOption | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const seqRef = useRef(createSequencer());

  /* ---- selected label (works for archived rows too) -------------------- */
  useEffect(() => {
    if (!value) {
      setSelected(null);
      return;
    }
    const cached = labelCache.get(value);
    if (cached) {
      setSelected(cached);
      return;
    }
    let alive = true;
    const supabase = createClient();
    supabase
      .from(table)
      .select(selectCols)
      .eq("id", value)
      .maybeSingle()
      .then(({ data }) => {
        if (!alive || !data) return;
        const opt = data as unknown as PartyOption;
        labelCache.set(opt.id, opt);
        setSelected(opt);
      });
    return () => {
      alive = false;
    };
  }, [value, table, selectCols]);

  /* ---- option loading: default page vs debounced search ---------------- */
  const loadOptions = useCallback(
    async (q: string, signal: AbortSignal) => {
      const supabase = createClient();
      const expr = ilikeAny(["name", codeCol, "email", "phone"], q);
      let query = supabase
        .from(table)
        .select(selectCols)
        .eq("organization_id", organizationId)
        .eq("is_active", true)
        .abortSignal(signal);
      if (expr) {
        query = query.or(expr).order("name", { ascending: true });
      } else {
        query = query.order("created_at", { ascending: false });
      }
      const { data, error } = await query.limit(OPTIONS_LIMIT);
      if (error) throw error;
      return ((data ?? []) as unknown as PartyOption[]).map((o) => {
        labelCache.set(o.id, o);
        return o;
      });
    },
    [table, codeCol, selectCols, organizationId]
  );

  // Debounce keystrokes → one query; previous options stay visible meanwhile.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => {
      const seq = seqRef.current.next();
      const controller = new AbortController();
      setLoading(true);
      try {
        const rows = await loadOptions(query, controller.signal);
        if (!seqRef.current.isCurrent(seq)) return;
        setOptions(rows);
        setActive(0);
        setListError(null);
      } catch (err) {
        if (!seqRef.current.isCurrent(seq)) return;
        if ((err as { name?: string })?.name === "AbortError") return;
        setListError(
          err instanceof Error
            ? err.message
            : `Couldn't load ${noun.toLowerCase()}s`
        );
      } finally {
        if (seqRef.current.isCurrent(seq)) setLoading(false);
      }
    }, query ? 200 : 0);
    return () => clearTimeout(t);
  }, [open, query, loadOptions, noun]);

  /* ---- recents (session picks) shown above the default list ------------ */
  const recentOptions = useMemo(() => {
    if (!open || query) return [];
    return recentListFor(table, organizationId)
      .list()
      .map((id) => labelCache.get(id))
      .filter((o): o is PartyOption => !!o && o.id !== value);
  }, [open, query, table, organizationId, value, options]); // eslint-disable-line react-hooks/exhaustive-deps

  // Flat keyboard list: recents first, then the loaded/search results.
  const flat = useMemo(() => {
    const seen = new Set<string>();
    const out: PartyOption[] = [];
    for (const o of [...recentOptions, ...options]) {
      if (seen.has(o.id)) continue;
      seen.add(o.id);
      out.push(o);
    }
    return out;
  }, [recentOptions, options]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setMode("list");
    setCreateError(null);
    setActive(0);
  }, []);

  // Outside click closes (same contract as AccountCombobox).
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

  const pick = useCallback(
    (option: PartyOption) => {
      recentListFor(table, organizationId).push(option.id);
      labelCache.set(option.id, option);
      setSelected(option);
      onChange(option.id, option);
      close();
    },
    [table, organizationId, onChange, close]
  );

  const handleCreate = useCallback(async () => {
    // Display-grade casing at the creation boundary ("motorbike" →
    // "Motorbike") — the same rule the backend repositories apply.
    const name = professionalName(createName);
    if (!organizationId || name.length < 2 || creating) return;
    setCreating(true);
    setCreateError(null);
    const supabase = createClient();
    const { data, error } = await supabase
      .from(table)
      .insert({
        organization_id: organizationId,
        name,
        ...(baseCurrency ? { currency_code: baseCurrency } : {}),
      })
      .select(selectCols)
      .single();
    setCreating(false);
    if (error || !data) {
      setCreateError(
        error?.message ?? `Couldn't create the ${noun.toLowerCase()}`
      );
      return;
    }
    const created = data as unknown as PartyOption;
    labelCache.set(created.id, created);
    recentListFor(table, organizationId).push(created.id);
    setSelected(created);
    setCreateName("");
    onChange(created.id, created);
    onCreated?.(created);
    close();
  }, [
    createName,
    creating,
    organizationId,
    baseCurrency,
    table,
    selectCols,
    noun,
    onChange,
    onCreated,
    close,
  ]);

  /* ---- keyboard + rendering --------------------------------------------- */
  const listboxId = `${inputId}-listbox`;
  const optionId = (id: string) => `${inputId}-opt-${id}`;

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (mode === "create") {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation(); // Escape closes the create row, not the modal
        setMode("list");
        setCreateError(null);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        handleCreate();
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) {
          setOpen(true);
          return;
        }
        setActive((i) => Math.min(i + 1, Math.max(0, flat.length - 1)));
        break;
      case "ArrowUp":
        e.preventDefault();
        if (!open) {
          setOpen(true);
          return;
        }
        setActive((i) => Math.max(0, i - 1));
        break;
      case "Enter": {
        if (!open) return;
        e.preventDefault();
        const option = flat[active];
        if (option) pick(option);
        break;
      }
      case "Escape":
        if (open) {
          e.preventDefault();
          e.stopPropagation(); // Escape closes the dropdown, not the modal
          close();
        }
        break;
      case "Tab":
        if (open) close();
        break;
      default:
        break;
    }
  };

  // Keep the active option inside the dropdown's own scroll window.
  useEffect(() => {
    if (!open) return;
    const el = document.getElementById(optionId(flat[active]?.id ?? ""));
    el?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, open, flat]);

  const rowCls = (isActive: boolean) =>
    cn(
      "w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors",
      isActive ? "bg-bg-muted" : "hover:bg-bg-muted/60"
    );



  const resultOptions = query
    ? flat
    : flat.filter((o) => !recentOptions.some((r) => r.id === o.id));

  return (
    <div ref={rootRef} className={cn("relative", className)}>
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
            open && flat[active] ? optionId(flat[active].id) : undefined
          }
          aria-label={label}
          autoComplete="off"
          disabled={disabled}
          className="w-full px-3 py-2 pr-8 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors disabled:opacity-60"
          placeholder={placeholder ?? `Search ${noun.toLowerCase()}s…`}
          value={open ? query : selected?.name ?? ""}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onClick={() => {
            if (!open) {
              setOpen(true);
              setQuery("");
            }
          }}
          onKeyDown={onKeyDown}
        />
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-text-muted">
          {loading && open ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <ChevronDown
              className={cn(
                "w-3.5 h-3.5 transition-transform",
                open && "rotate-180"
              )}
            />
          )}
        </span>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-40 bg-bg-surface rounded-xl shadow-lg border border-border-subtle overflow-hidden">
          {mode === "create" ? (
            <div className="p-3 space-y-2">
              <p className="text-xs font-medium text-text-secondary">
                New {noun.toLowerCase()}
              </p>
              <input
                autoFocus
                className="w-full px-3 py-2 rounded-lg bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300"
                placeholder={`${noun} name`}
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                onKeyDown={onKeyDown}
                aria-label={`New ${noun.toLowerCase()} name`}
              />
              {createError && (
                <p className="text-xs text-error-600 bg-error-50 rounded-lg px-2.5 py-1.5">
                  {createError}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
                  onClick={() => {
                    setMode("list");
                    setCreateError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={creating || createName.trim().length < 2}
                  onClick={handleCreate}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-ai-600 hover:bg-ai-700 disabled:opacity-40 transition-colors"
                >
                  {creating ? "Creating…" : "Create & select"}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div
                id={listboxId}
                role="listbox"
                aria-label={label}
                className="max-h-64 overflow-y-auto overscroll-contain py-1"
              >
                {listError ? (
                  <p className="px-3 py-4 text-xs text-error-600 text-center">
                    {listError}
                  </p>
                ) : flat.length === 0 && !loading ? (
                  <p className="px-3 py-4 text-xs text-text-muted text-center">
                    {query
                      ? `No ${noun.toLowerCase()}s match “${query}”.`
                      : `No ${noun.toLowerCase()}s yet.`}
                  </p>
                ) : (
                  <>
                    {!query && recentOptions.length > 0 && (
                      <p className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-widest text-text-muted">
                        Recent
                      </p>
                    )}
                    {!query && recentOptions.length === 0 && resultOptions.length > 0 && (
                      <p className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-widest text-text-muted">
                        Recently added
                      </p>
                    )}
                    {resultOptions.map((o) => {
                      const flatIndex = flat.findIndex((f) => f.id === o.id);
                      return (
                        <button
                          key={o.id}
                          type="button"
                          id={optionId(o.id)}
                          role="option"
                          aria-selected={o.id === value}
                          className={rowCls(flatIndex === active)}
                          onMouseEnter={() => setActive(flatIndex)}
                          onClick={() => pick(o)}
                        >
                          <span className="truncate text-text-primary">
                            {o.name}
                          </span>
                          <span className="flex items-center gap-1.5 shrink-0">
                            {o.code && (
                              <span className="text-[11px] text-text-muted tabular-nums">
                                {o.code}
                              </span>
                            )}
                            {o.id === value && (
                              <Check className="w-3.5 h-3.5 text-ai-600" />
                            )}
                          </span>
                        </button>
                      );
                    })}
                  </>
                )}
              </div>
              {allowCreate && (
                <button
                  type="button"
                  className="w-full flex items-center gap-2 px-3 py-2.5 text-sm font-medium text-ai-700 bg-ai-50/60 hover:bg-ai-50 border-t border-border-subtle transition-colors"
                  onClick={() => {
                    setMode("create");
                    setCreateName(query);
                    setCreateError(null);
                  }}
                >
                  <Plus className="w-4 h-4" /> Create new {noun.toLowerCase()}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

