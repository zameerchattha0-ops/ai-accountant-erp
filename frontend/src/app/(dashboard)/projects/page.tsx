"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Search } from "lucide-react";
import {
  createProject,
  listProjects,
  updateProject,
  type ProjectRegister,
  type ProjectRow,
} from "@/lib/api/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import {
  BILLING_TYPES,
  EMPTY_PROJECT_FORM,
  PROJECT_STATUSES,
  STATUS_FILTERS,
  formatMargin,
  humanise,
  messageOf,
  pnlState,
  projectFormBlocker,
  projectFormFrom,
  projectPayload,
  visibleProjects,
  type ProjectFormValues,
} from "@/lib/projects/logic";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const EMPTY_SUMMARY = { budget: 0, revenue: 0, costs: 0, gross_profit: 0 };

/** How long to wait after the last keystroke before asking the server. */
const SEARCH_DEBOUNCE_MS = 300;

export default function ProjectsPage() {
  const { org, loading: orgLoading } = useOrg();

  const [register, setRegister] = useState<ProjectRegister | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");

  const [modalOpen, setModalOpen] = useState(false);
  /** null = creating a new project; a row = editing that project. */
  const [editing, setEditing] = useState<ProjectRow | null>(null);
  const [form, setForm] = useState<ProjectFormValues>(EMPTY_PROJECT_FORM);
  /** The user has touched the form — only then do we show a red refusal. */
  const [touched, setTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Server-side search results — used ONLY when the loaded register is
  // incomplete (see `truncated`); null means "use the loaded page".
  const [serverItems, setServerItems] = useState<ProjectRow[] | null>(null);
  const [searching, setSearching] = useState(false);

  const currency = org?.base_currency_code;
  const money = useCallback(
    (value: number | null | undefined) =>
      formatCurrency(Number(value ?? 0), currency),
    [currency]
  );

  const load = useCallback(async () => {
    if (!org) return;
    try {
      setError(null);
      setRegister(await listProjects());
    } catch (e) {
      setError(messageOf(e));
    }
  }, [org]);

  useEffect(() => {
    void load();
  }, [load]);

  // Memoised so the identity is stable between renders — otherwise the two
  // useMemo hooks below would re-run on every render (exhaustive-deps).
  const rows = useMemo(() => register?.items ?? [], [register]);
  const counts = register?.counts ?? {};
  const summary = register?.summary ?? EMPTY_SUMMARY;
  const customers = useMemo(() => register?.customers ?? [], [register]);

  // Honesty signals from the register (see ProjectRegister): which lookups are
  // usable, and whether the loaded list is a complete picture.
  const degraded = register?.degraded ?? [];
  const profitabilityKnown = !degraded.includes("profitability");
  const customersKnown = !degraded.includes("customers");
  const truncated = register?.truncated ?? false;

  const filtered = useMemo(
    () => visibleProjects(rows, search, status, serverItems, truncated),
    [rows, search, status, serverItems, truncated]
  );

  const blocker = projectFormBlocker(form);

  /**
   * Server-side search: needed only when the loaded page is INCOMPLETE (the
   * register exceeded the read ceiling) — then the browser's copy can no longer
   * answer the query.  Debounced so typing stays smooth, and the previous list
   * stays visible while it runs (no flicker).
   */
  useEffect(() => {
    if (!truncated || !org) {
      setServerItems(null);
      return;
    }
    const handle = setTimeout(async () => {
      setSearching(true);
      try {
        const result = await listProjects(search, status);
        setServerItems(result.items);
      } catch {
        // Fall back to the loaded page rather than blanking the list.
        setServerItems(null);
      } finally {
        setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [truncated, org, register, search, status]);

  /**
   * The customer picker's options.  The edited project's OWN customer is kept
   * even when the register's customer list could not be read — a failed lookup
   * must never silently drop a linked customer from the form.
   */
  const customerOptions = useMemo(() => {
    const options = customers.map((c) => ({ id: c.id, name: c.name }));
    if (form.customer_id && !options.some((o) => o.id === form.customer_id)) {
      options.push({
        id: form.customer_id,
        name: editing?.customer_name ?? "Linked customer",
      });
    }
    return options;
  }, [customers, form.customer_id, editing]);

  /** Any edit marks the form touched so a refusal shows only once asked for. */
  const update = (patch: Partial<ProjectFormValues>) => {
    setTouched(true);
    setForm((prev) => ({ ...prev, ...patch }));
  };

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_PROJECT_FORM);
    setTouched(false);
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (project: ProjectRow) => {
    setEditing(project);
    setForm(projectFormFrom(project));
    setTouched(false);
    setFormError(null);
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (saving) return; // a second click while the request is in flight is ignored
    setTouched(true);
    if (projectFormBlocker(form)) return; // the inline refusal already explains why
    setSaving(true);
    setFormError(null);
    try {
      const payload = projectPayload(form);
      if (editing) {
        await updateProject(editing.id, payload);
      } else {
        await createProject({ ...payload, currency_code: currency || "PKR" });
      }
      setModalOpen(false);
      await load();
    } catch (e) {
      setFormError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  /**
   * Honest state banners.  Each names a real limitation instead of hiding it:
   * a capped register, or a lookup that failed (so its figures read "—").
   */
  const notices: string[] = [];
  if (truncated && register) {
    notices.push(
      `Only the first ${register.total} projects are shown — this register is ` +
        "larger, and the totals describe these projects only."
    );
  }
  if (!profitabilityKnown && register) {
    notices.push(
      "Live profitability could not be loaded just now, so project revenue, " +
        "costs and profit are shown as “—”. The register itself is unaffected."
    );
  }
  if (!customersKnown && register) {
    notices.push("Customer names could not be loaded just now.");
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Projects"
        subtitle="Track projects, their budgets and their live P&L — every figure is posted from real journal lines, never estimated."
        actions={
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 px-3.5 py-2 text-sm font-semibold text-white hover:from-ai-400 transition"
          >
            <Plus className="w-4 h-4" />
            New project
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Active projects", value: String(counts.ACTIVE ?? 0) },
          { label: "Total budget", value: money(summary.budget) },
          {
            label: "Revenue (posted)",
            // "—" (unknown) beats Rs 0.00 when the lookup failed — a bare zero
            // would read as "these projects earned nothing".
            value: profitabilityKnown ? money(summary.revenue) : "—",
          },
          {
            label: "Gross profit",
            value: profitabilityKnown ? money(summary.gross_profit) : "—",
          },
        ].map((card) => (
          <div
            key={card.label}
            className="bg-bg-surface rounded-2xl border border-border-subtle p-4"
          >
            <p className="text-[11px] uppercase tracking-wide text-text-muted">
              {card.label}
            </p>
            <p className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {card.value}
            </p>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by project name, code or customer..."
            className={`${inputCls} pl-9`}
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={`${inputCls} sm:w-60`}
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option} value={option}>
              {option === "ALL"
                ? `All projects (${counts.ALL ?? rows.length})`
                : `${humanise(option)} (${counts[option] ?? 0})`}
            </option>
          ))}
        </select>
      </div>

      {searching && (
        <p className="text-xs text-text-muted">Searching the full register…</p>
      )}

      {notices.length > 0 && (
        <div className="rounded-xl border border-warning-100 bg-warning-50 px-4 py-3 text-sm text-text-primary space-y-1">
          {notices.map((notice) => (
            <p key={notice}>{notice}</p>
          ))}
        </div>
      )}

      {orgLoading || (!register && !error) ? (
        <TableSkeleton cols={8} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={rows.length ? "No projects match this filter" : "No projects yet"}
          hint={
            rows.length
              ? undefined
              : "Create one here, or tell the AI agent: \"Set up a project called Mobile App for a client with a budget of 2,000,000\"."
          }
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Code</th>
                <th className="px-4 py-3 font-medium">Project</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Timeline</th>
                <th className="px-4 py-3 font-medium text-right">Budget</th>
                <th className="px-4 py-3 font-medium text-right">Revenue</th>
                <th className="px-4 py-3 font-medium text-right">Costs</th>
                <th className="px-4 py-3 font-medium text-right">Gross profit</th>
                <th className="px-4 py-3 font-medium text-right">Margin</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((project) => {
                const state = pnlState(project, profitabilityKnown);
                const showPnl = state === "posted";
                const pnlHint =
                  state === "unknown"
                    ? "Profitability could not be loaded"
                    : state === "none"
                      ? "No posted journal lines yet"
                      : undefined;
                return (
                  <tr
                    key={project.id}
                    className="border-b border-border-subtle/60 last:border-0 hover:bg-bg-muted/50 transition-colors"
                  >
                    <td className="px-4 py-3 text-text-secondary tabular-nums">
                      {project.project_code ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-medium text-text-primary">
                      {project.name}
                      {project.description ? (
                        <span className="block text-xs font-normal text-text-muted">
                          {project.description}
                        </span>
                      ) : null}
                    </td>
                    <td
                      className="px-4 py-3 text-text-secondary"
                      title={
                        !customersKnown && project.customer_id
                          ? "Customer names could not be loaded"
                          : undefined
                      }
                    >
                      {project.customer_name ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={project.status} />
                    </td>
                    <td className="px-4 py-3 text-text-secondary tabular-nums whitespace-nowrap">
                      {(project.start_date ?? "—").slice(0, 10)} →{" "}
                      {(project.end_date ?? "—").slice(0, 10)}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {project.budget != null ? money(project.budget) : "—"}
                    </td>
                    <td
                      className="px-4 py-3 text-right text-text-secondary tabular-nums"
                      title={pnlHint}
                    >
                      {showPnl ? (
                        money(project.revenue)
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td
                      className="px-4 py-3 text-right text-text-secondary tabular-nums"
                      title={pnlHint}
                    >
                      {showPnl ? (
                        money(project.costs)
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td
                      className="px-4 py-3 text-right font-medium text-text-primary tabular-nums"
                      title={pnlHint}
                    >
                      {showPnl ? (
                        money(project.gross_profit)
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-text-secondary tabular-nums">
                      {showPnl ? formatMargin(project.margin_percent) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end">
                        <button
                          onClick={() => openEdit(project)}
                          title="Edit this project's details"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:border-ai-300 transition-colors"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? "Edit project" : "New project"}
      >
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-text-secondary">
              Name *
            </label>
            <input
              className={`${inputCls} mt-1.5`}
              value={form.name}
              autoFocus
              onChange={(e) => update({ name: e.target.value })}
              placeholder="e.g. Mobile App"
            />
            {editing && (
              <p className="mt-1 text-[11px] text-text-muted">
                Code {editing.project_code} is assigned by the system and cannot
                be changed.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Customer
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.customer_id}
                onChange={(e) => update({ customer_id: e.target.value })}
              >
                <option value="">No customer</option>
                {customerOptions.map((customer) => (
                  <option key={customer.id} value={customer.id}>
                    {customer.name}
                  </option>
                ))}
              </select>
              {customers.length === 0 && (
                <p className="mt-1 text-[11px] text-text-muted">
                  No customers on file — a project does not need one; you can
                  link it later.
                </p>
              )}
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Status
              </label>
              <select
                className={`${inputCls} mt-1.5`}
                value={form.status}
                onChange={(e) => update({ status: e.target.value })}
              >
                {PROJECT_STATUSES.map((option) => (
                  <option key={option} value={option}>
                    {humanise(option)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">
              Billing type
            </label>
            <select
              className={`${inputCls} mt-1.5`}
              value={form.billing_type}
              onChange={(e) => update({ billing_type: e.target.value })}
            >
              <option value="">Not set</option>
              {BILLING_TYPES.map((option) => (
                <option key={option} value={option}>
                  {humanise(option)}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-text-secondary">
                Start date
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                type="date"
                value={form.start_date}
                onChange={(e) => update({ start_date: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">
                End date
              </label>
              <input
                className={`${inputCls} mt-1.5`}
                type="date"
                value={form.end_date}
                onChange={(e) => update({ end_date: e.target.value })}
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">
              Budget
            </label>
            <input
              className={`${inputCls} mt-1.5`}
              inputMode="decimal"
              value={form.budget}
              onChange={(e) => update({ budget: e.target.value })}
              placeholder="2000000"
            />
            <p className="mt-1 text-[11px] text-text-muted">
              Leave blank for &quot;no budget&quot; — a blank is never stored as
              zero.
            </p>
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary">
              Description
            </label>
            <textarea
              className={`${inputCls} mt-1.5`}
              rows={2}
              value={form.description}
              onChange={(e) => update({ description: e.target.value })}
              placeholder="What is this project about?"
            />
          </div>

          {/* The refusal the server would give is shown here FIRST — the user
              never learns a rule from a 409. */}
          {touched && blocker && (
            <p className="text-xs text-warning-700">{blocker}</p>
          )}
          {formError && <p className="text-xs text-error-600">{formError}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl border border-border-default text-sm text-text-secondary hover:bg-bg-secondary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => void handleSave()}
              disabled={saving || (touched && blocker !== null)}
              className="px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
            >
              {saving
                ? "Saving..."
                : editing
                  ? "Save changes"
                  : "Create project"}
            </button>
          </div>
        </div>
      </Modal>

    </div>
  );
}

