"use client";

import { useState } from "react";
import { Plus, Search, Sparkles, CheckCircle2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { ilikeAny } from "@/lib/lists/logic";
import { formatCurrency } from "@/lib/utils/currency";
import { aiExecute, aiClarify, aiConfirm } from "@/lib/api/client";
import type { AgentResponse } from "@/lib/types/api";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Employee } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";
const labelCls = "block text-xs font-medium text-text-secondary";

interface EmployeeForm {
  full_name: string;
  date_of_joining: string;
  basic_salary: string;
  designation: string;
  department: string;
  employment_type: string;
  phone: string;
  email: string;
  cnic: string;
  bank_name: string;
  bank_account_number: string;
  pay_day: string;
  notes: string;
}

const EMPTY_FORM: EmployeeForm = {
  full_name: "",
  date_of_joining: "",
  basic_salary: "",
  designation: "",
  department: "",
  employment_type: "",
  phone: "",
  email: "",
  cnic: "",
  bank_name: "",
  bank_account_number: "",
  pay_day: "",
  notes: "",
};

/**
 * The AI's card for the natural-language allowance round.  The sentence is
 * structured by the MODEL (never by this page) — the UI only renders what
 * the agent answers: a question to answer, a confirmation to approve, or
 * the completion summary.
 */
type AiCard =
  | { kind: "working"; text: string }
  | { kind: "question"; sessionId: string; text: string; options: string[] }
  | { kind: "confirm"; sessionId: string; text: string }
  | { kind: "done"; text: string }
  | { kind: "error"; text: string };

function cardFromResponse(resp: AgentResponse): AiCard {
  if (resp.execution_id && resp.requires_user_input && resp.question) {
    return {
      kind: "question",
      sessionId: resp.execution_id,
      text: resp.question,
      options: resp.options ?? [],
    };
  }
  if (resp.confirmation_required) {
    return {
      kind: "confirm",
      sessionId: resp.execution_id ?? "",
      text:
        resp.summary ||
        "The AI is ready to record the allowances — confirm to proceed.",
    };
  }
  return {
    kind: "done",
    text: resp.summary || "The allowances were recorded.",
  };
}

export default function EmployeesPage() {
  const { org, loading: orgLoading } = useOrg();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<EmployeeForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // "gets allowances?" checkbox + the natural-language box behind it
  const [hasAllowances, setHasAllowances] = useState(false);
  const [allowanceText, setAllowanceText] = useState("");
  // the agent's round for the allowance sentence
  const [ai, setAi] = useState<AiCard | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiAnswer, setAiAnswer] = useState("");
  const [lastAiRequest, setLastAiRequest] = useState<{
    employee: Employee;
    text: string;
  } | null>(null);

  // SERVER-SIDE LIST: name / code / department / designation / email search
  // and paging run in the database — one page of rows in the browser.
  const {
    rows, error, refreshing, search, setSearch,
    page, setPage, pageSize, count, refresh,
  } = useServerList<Employee>({
    enabled: !!org,
    fetchPage: async ({ page, pageSize, search, signal }) => {
      if (!org) return { rows: [], count: 0 };
      const supabase = createClient();
      let query = supabase
        .from("employees")
        .select(
          "id, employee_code, full_name, date_of_joining, basic_salary, status, designation, department, is_active",
          { count: "exact" }
        )
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false })
        .order("id", { ascending: true })
        .range(page * pageSize, page * pageSize + pageSize - 1)
        .abortSignal(signal);
      const expr = ilikeAny(
        ["full_name", "employee_code", "department", "designation", "email"],
        search
      );
      if (expr) query = query.or(expr);
      const { data, error: dbError, count: total } = await query;
      if (dbError) throw dbError;
      return { rows: (data ?? []) as unknown as Employee[], count: total ?? null };
    },
  });

  /** Talk to the agent for the allowance sentence — the MODEL structures it. */
  const runAllowanceAi = async (employee: Employee, text: string) => {
    setLastAiRequest({ employee, text });
    setAi({
      kind: "working",
      text: "The AI is reading your description and structuring the allowances…",
    });
    setAiBusy(true);
    try {
      const resp = await aiExecute({
        message:
          `Set allowances for employee ${employee.employee_code ?? ""} ` +
          `(${employee.full_name}). User's description: ${text}`,
        conversation_id:
          typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : `emp-${Date.now()}`,
      });
      setAi(cardFromResponse(resp));
    } catch (e) {
      setAi({
        kind: "error",
        text: e instanceof Error ? e.message : "The AI request failed.",
      });
    } finally {
      setAiBusy(false);
    }
  };

  const replyToAi = async (reply: () => Promise<AgentResponse>) => {
    setAiBusy(true);
    setAi({ kind: "working", text: "The AI is thinking…" });
    try {
      setAi(cardFromResponse(await reply()));
    } catch (e) {
      setAi({
        kind: "error",
        text: e instanceof Error ? e.message : "The AI request failed.",
      });
    } finally {
      setAiBusy(false);
    }
  };

  const handleSave = async () => {
    if (!org) return;
    if (form.full_name.trim().length < 2) {
      setFormError("Full name is required.");
      return;
    }
    if (!form.date_of_joining) {
      setFormError("Date of joining is required.");
      return;
    }
    const salary = Number(String(form.basic_salary).replace(/,/g, ""));
    if (!Number.isFinite(salary) || salary <= 0) {
      setFormError("Basic salary must be greater than zero.");
      return;
    }
    const allowanceTextClean = allowanceText.trim();
    if (hasAllowances && !allowanceTextClean) {
      setFormError(
        'Tick "gets allowances" — describe them in your own words, or untick it.',
      );
      return;
    }
    setSaving(true);
    setFormError(null);
    const supabase = createClient();
    const payload: Record<string, unknown> = {
      organization_id: org.organization_id,
      full_name: form.full_name.trim(),
      date_of_joining: form.date_of_joining,
      basic_salary: salary,
    };
    const optionalText: [keyof EmployeeForm, string][] = [
      ["designation", "designation"],
      ["department", "department"],
      ["employment_type", "employment_type"],
      ["phone", "phone"],
      ["email", "email"],
      ["cnic", "cnic"],
      ["bank_name", "bank_name"],
      ["bank_account_number", "bank_account_number"],
      ["notes", "notes"],
    ];
    for (const [key, column] of optionalText) {
      const value = String(form[key] ?? "").trim();
      if (value) payload[column] = value;
    }
    if (form.pay_day.trim()) {
      const day = Number(form.pay_day);
      if (!Number.isInteger(day) || day < 1 || day > 31) {
        setSaving(false);
        setFormError("Pay day must be between 1 and 31.");
        return;
      }
      payload.pay_day = day;
    }

    const { data: created, error: insertError } = await supabase
      .from("employees")
      .insert(payload)
      .select()
      .single();
    if (insertError) {
      setSaving(false);
      setFormError(insertError.message);
      return;
    }
    refresh();
    setSaving(false);
    setModalOpen(false);
    setForm(EMPTY_FORM);
    setHasAllowances(false);
    setAllowanceText("");
    if (created) {
      if (allowanceTextClean) {
        void runAllowanceAi(created as Employee, allowanceTextClean);
      }
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        subtitle="Name, joining date and basic salary are all you need — the AI records the rest"
        actions={
          <button
            onClick={() => { setForm(EMPTY_FORM); setFormError(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus size={16} /> Add employee
          </button>
        }
      />

      {/* The agent's round for the natural-language allowance description.
          The MODEL structures the sentence — this card only shows the
          agent's question / confirmation / result. */}
      {ai && (
        <div className="rounded-2xl border border-ai-200 bg-ai-50/60 p-4 space-y-3">
          {ai.kind === "working" && (
            <div className="flex items-center gap-2 text-sm text-text-secondary">
              <Sparkles size={16} className="text-ai-500 animate-pulse" />
              {ai.text}
            </div>
          )}
          {ai.kind === "question" && (
            <>
              <div className="text-sm text-text-primary whitespace-pre-line font-medium">
                {ai.text}
              </div>
              {ai.options.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {ai.options.map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      disabled={aiBusy}
                      onClick={() => setAiAnswer(opt)}
                      className="px-3 py-1.5 rounded-full border border-ai-300 bg-bg-surface text-xs font-medium text-text-primary hover:bg-ai-50 transition-colors"
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <input
                  className={inputCls}
                  value={aiAnswer}
                  disabled={aiBusy}
                  onChange={(e) => setAiAnswer(e.target.value)}
                  placeholder="Type your answer…"
                />
                <button
                  type="button"
                  disabled={aiBusy || !aiAnswer.trim()}
                  onClick={() => {
                    const answer = aiAnswer.trim();
                    if (!answer) return;
                    setAiAnswer("");
                    void replyToAi(() =>
                      aiClarify({ session_id: ai.sessionId, answer }),
                    );
                  }}
                  className="px-4 rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
                >
                  Send
                </button>
              </div>
            </>
          )}
          {ai.kind === "confirm" && (
            <>
              <div className="flex items-start gap-2 text-sm text-text-primary">
                <Sparkles size={16} className="text-ai-500 mt-0.5 shrink-0" />
                <span className="whitespace-pre-line">{ai.text}</span>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={aiBusy || !ai.sessionId}
                  onClick={() =>
                    void replyToAi(() =>
                      aiConfirm({ session_id: ai.sessionId, approved: true }),
                    )
                  }
                  className="px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={aiBusy || !ai.sessionId}
                  onClick={() =>
                    void replyToAi(() =>
                      aiConfirm({ session_id: ai.sessionId, approved: false }),
                    )
                  }
                  className="px-4 py-2 rounded-xl border border-border-default bg-bg-surface text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
          {ai.kind === "done" && (
            <div className="flex items-start gap-2 text-sm text-text-primary">
              <CheckCircle2 size={16} className="text-emerald-600 mt-0.5 shrink-0" />
              <span className="whitespace-pre-line">{ai.text}</span>
              <button
                type="button"
                onClick={() => setAi(null)}
                className="ml-auto text-xs font-medium text-text-muted hover:text-text-primary"
              >
                Dismiss
              </button>
            </div>
          )}
          {ai.kind === "error" && (
            <div className="flex items-start gap-2 text-sm text-text-primary">
              <AlertCircle size={16} className="text-red-500 mt-0.5 shrink-0" />
              <span>{ai.text}</span>
              <span className="ml-auto flex gap-3">
                {lastAiRequest && (
                  <button
                    type="button"
                    disabled={aiBusy}
                    onClick={() =>
                      void runAllowanceAi(
                        lastAiRequest.employee,
                        lastAiRequest.text,
                      )
                    }
                    className="text-xs font-medium text-ai-600 hover:underline"
                  >
                    Retry
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setAi(null)}
                  className="text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Dismiss
                </button>
              </span>
            </div>
          )}
        </div>
      )}

      <div className="relative max-w-md">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
        />
        <input
          className={`${inputCls} pl-9`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, code, department, designation or email…"
          aria-label="Search employees"
        />
      </div>

      {orgLoading || (!rows && !error) ? (
        <TableSkeleton cols={5} />
      ) : error ? (
        <ErrorState message={error} />
      ) : (rows ?? []).length === 0 ? (
        <EmptyState
          title={search ? "No employees match your search" : "No employees yet"}
          hint={
            search
              ? undefined
              : 'Add your first employee with just a name, joining date and basic salary — or tell the AI: "Add employee Ayesha Khan who joined on 1 March 2026 with a salary of 120,000".'
          }
        />
      ) : (
        <div className={`bg-bg-surface rounded-2xl border border-border-subtle overflow-x-auto transition-opacity ${refreshing ? "opacity-60" : ""}`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-4 py-3 font-medium">Employee</th>
                <th className="px-4 py-3 font-medium">Joined</th>
                <th className="px-4 py-3 font-medium">Department</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Basic salary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {(rows ?? []).map((e) => (
                <tr key={e.id} className="hover:bg-bg-primary/60 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-text-primary">
                      {e.full_name}
                    </div>
                    <div className="text-xs text-text-muted">
                      {[e.employee_code, e.designation]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {e.date_of_joining}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {e.department || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={e.is_active ? e.status : "VOIDED"} />
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-text-primary">
                    {formatCurrency(e.basic_salary)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination
        page={page}
        pageSize={pageSize}
        count={count}
        onPageChange={setPage}
        refreshing={refreshing}
      />

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add employee">
        <div className="space-y-4">
          <div>
            <label className={labelCls}>Full name *</label>
            <input
              className={`${inputCls} mt-1.5`}
              value={form.full_name}
              autoFocus
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder="e.g. Ayesha Khan"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Date of joining *</label>
              <input
                type="date"
                className={`${inputCls} mt-1.5`}
                value={form.date_of_joining}
                onChange={(e) =>
                  setForm({ ...form, date_of_joining: e.target.value })
                }
              />
            </div>
            <div>
              <label className={labelCls}>Basic salary (monthly) *</label>
              <input
                type="number"
                min={0}
                step="any"
                className={`${inputCls} mt-1.5`}
                value={form.basic_salary}
                onChange={(e) =>
                  setForm({ ...form, basic_salary: e.target.value })
                }
                placeholder="e.g. 120000"
              />
            </div>
          </div>

          {/* Allowance checkmark → the natural-language box → the AI */}
          <div className="rounded-xl border border-ai-200 bg-ai-50/40 p-3 space-y-3">
            <label className="flex items-center gap-2 text-sm text-text-primary cursor-pointer">
              <input
                type="checkbox"
                checked={hasAllowances}
                onChange={(e) => setHasAllowances(e.target.checked)}
                className="h-4 w-4 rounded border-border-default text-ai-500 focus:ring-ai-400"
              />
              This employee receives allowances (rent, fuel, medical…)
            </label>
            {hasAllowances && (
              <div>
                <label className={labelCls}>
                  Describe the allowances in your own words — the AI records
                  the line items
                </label>
                <textarea
                  rows={3}
                  className={`${inputCls} mt-1.5 resize-y`}
                  value={allowanceText}
                  onChange={(e) => setAllowanceText(e.target.value)}
                  placeholder={'e.g. "house rent 25,000 per month, fuel 10,000 per month and a one-time medical of 30,000"'}
                />
                <p className="mt-1.5 text-xs text-text-muted">
                  Sent to the AI after saving — it structures each allowance
                  and asks you to confirm.
                </p>
              </div>
            )}
          </div>

          <details className="rounded-xl border border-border-subtle">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-text-secondary hover:text-text-primary">
              More details (all optional)
            </summary>
            <div className="px-3 pb-3 pt-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {([
                ["designation", "Designation", "e.g. Driver"],
                ["department", "Department", "e.g. Operations"],
                ["employment_type", "Employment type", "FULL_TIME / CONTRACT / INTERN"],
                ["phone", "Phone", ""],
                ["email", "Email", ""],
                ["cnic", "CNIC / National ID", ""],
                ["bank_name", "Bank", ""],
                ["bank_account_number", "Bank account / IBAN", ""],
                ["pay_day", "Pay day (1-31)", ""],
              ] as const).map(([key, labelText, placeholder]) => (
                <div key={key}>
                  <label className={labelCls}>{labelText}</label>
                  <input
                    className={`${inputCls} mt-1.5`}
                    value={form[key]}
                    onChange={(e) =>
                      setForm({ ...form, [key]: e.target.value } as EmployeeForm)
                    }
                    placeholder={placeholder}
                  />
                </div>
              ))}
              <div className="sm:col-span-2">
                <label className={labelCls}>Notes</label>
                <textarea
                  rows={2}
                  className={`${inputCls} mt-1.5 resize-y`}
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                />
              </div>
            </div>
          </details>

          {formError && <p className="text-sm text-red-500">{formError}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="px-4 py-2 rounded-xl border border-border-default text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
            >
              {saving
                ? "Saving…"
                : hasAllowances && allowanceText.trim()
                  ? "Save & send to AI"
                  : "Save employee"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}



