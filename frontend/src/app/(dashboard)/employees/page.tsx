"use client";

import { useState } from "react";
import {
  Plus,
  Search,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Pencil,
  Eye,
  UserRound,
  Briefcase,
  CreditCard,
  Phone,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { useServerList } from "@/lib/hooks/useServerList";
import { ilikeAny } from "@/lib/lists/logic";
import { professionalName } from "@/lib/utils/displayName";
import { formatCurrency } from "@/lib/utils/currency";
import { aiExecute, aiClarify, aiConfirm } from "@/lib/api/client";
import type { AgentResponse } from "@/lib/types/api";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import Pagination from "@/components/shared/Pagination";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type { Employee, EmployeeAllowance } from "@/lib/types/entities";

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
  status?: string;
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
  status: "ACTIVE",
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

  // Full Details & Edit state
  const [selectedEmployee, setSelectedEmployee] = useState<Employee | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"details" | "edit" | "allowances">("details");
  const [editForm, setEditForm] = useState<EmployeeForm>(EMPTY_FORM);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [employeeAllowances, setEmployeeAllowances] = useState<EmployeeAllowance[]>([]);
  const [loadingAllowances, setLoadingAllowances] = useState(false);

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
        .select("*", { count: "exact" })
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

  const openDetails = async (e: Employee) => {
    setSelectedEmployee(e);
    setActiveTab("details");
    setDetailsOpen(true);
    setLoadingAllowances(true);
    if (org) {
      const supabase = createClient();
      const { data } = await supabase
        .from("employee_allowances")
        .select("*")
        .eq("employee_id", e.id)
        .eq("organization_id", org.organization_id)
        .order("created_at", { ascending: false });
      setEmployeeAllowances((data ?? []) as unknown as EmployeeAllowance[]);
    }
    setLoadingAllowances(false);
  };

  const openEdit = (e: Employee) => {
    setSelectedEmployee(e);
    setEditForm({
      full_name: e.full_name || "",
      date_of_joining: e.date_of_joining || "",
      basic_salary: e.basic_salary != null ? String(e.basic_salary) : "",
      designation: e.designation || "",
      department: e.department || "",
      employment_type: e.employment_type || "",
      status: e.status || "ACTIVE",
      phone: e.phone || "",
      email: e.email || "",
      cnic: e.cnic || "",
      bank_name: e.bank_name || "",
      bank_account_number: e.bank_account_number || "",
      pay_day: e.pay_day != null ? String(e.pay_day) : "",
      notes: e.notes || "",
    });
    setEditError(null);
    setActiveTab("edit");
    setDetailsOpen(true);
  };

  const handleUpdateEmployee = async () => {
    if (!org || !selectedEmployee) return;
    if (editForm.full_name.trim().length < 2) {
      setEditError("Full name is required (at least 2 characters).");
      return;
    }
    if (!editForm.date_of_joining) {
      setEditError("Date of joining is required.");
      return;
    }
    const salary = Number(String(editForm.basic_salary).replace(/,/g, ""));
    if (!Number.isFinite(salary) || salary <= 0) {
      setEditError("Basic salary must be greater than zero.");
      return;
    }

    setSavingEdit(true);
    setEditError(null);

    const payload: Record<string, unknown> = {
      full_name: professionalName(editForm.full_name),
      date_of_joining: editForm.date_of_joining,
      basic_salary: salary,
      status: editForm.status || "ACTIVE",
      designation: editForm.designation.trim() || null,
      department: editForm.department.trim() || null,
      employment_type: editForm.employment_type.trim() || null,
      phone: editForm.phone.trim() || null,
      email: editForm.email.trim() || null,
      cnic: editForm.cnic.trim() || null,
      bank_name: editForm.bank_name.trim() || null,
      bank_account_number: editForm.bank_account_number.trim() || null,
      notes: editForm.notes.trim() || null,
    };

    if (editForm.pay_day && editForm.pay_day.trim()) {
      const day = Number(editForm.pay_day);
      if (!Number.isInteger(day) || day < 1 || day > 31) {
        setSavingEdit(false);
        setEditError("Pay day must be between 1 and 31.");
        return;
      }
      payload.pay_day = day;
    } else {
      payload.pay_day = null;
    }

    const supabase = createClient();
    const { data: updated, error: updError } = await supabase
      .from("employees")
      .update(payload)
      .eq("id", selectedEmployee.id)
      .eq("organization_id", org.organization_id)
      .select()
      .single();

    setSavingEdit(false);
    if (updError) {
      setEditError(updError.message);
      return;
    }

    if (updated) {
      setSelectedEmployee(updated as unknown as Employee);
    }
    refresh();
    setActiveTab("details");
  };

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
      full_name: professionalName(form.full_name),
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
        void runAllowanceAi(created as unknown as Employee, allowanceTextClean);
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

      {/* The agent's round for the natural-language allowance description. */}
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
        <TableSkeleton cols={6} />
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
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {(rows ?? []).map((e) => (
                <tr
                  key={e.id}
                  onClick={() => void openDetails(e)}
                  className="hover:bg-bg-primary/80 cursor-pointer transition-colors group"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-text-primary group-hover:text-ai-600 transition-colors">
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
                  <td className="px-4 py-3 text-right" onClick={(ev) => ev.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => openEdit(e)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border-default bg-bg-surface text-xs font-medium text-text-secondary hover:text-text-primary hover:border-border-strong hover:bg-bg-primary transition-colors"
                        title="Edit employee details"
                      >
                        <Pencil size={13} />
                        <span>Edit</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void openDetails(e)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border-default bg-bg-surface text-xs font-medium text-text-secondary hover:text-text-primary hover:border-border-strong hover:bg-bg-primary transition-colors"
                        title="View full details"
                      >
                        <Eye size={13} />
                        <span>View</span>
                      </button>
                    </div>
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

      {/* Employee Full Details & Edit Modal */}
      {selectedEmployee && (
        <Modal
          open={detailsOpen}
          onClose={() => setDetailsOpen(false)}
          title={`Employee — ${selectedEmployee.full_name} (${selectedEmployee.employee_code ?? "EMP"})`}
          wide
        >
          <div className="space-y-5">
            {/* Tab navigation */}
            <div className="flex items-center gap-2 border-b border-border-subtle pb-2">
              <button
                type="button"
                onClick={() => setActiveTab("details")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === "details"
                    ? "bg-ai-50 text-ai-700 border border-ai-200"
                    : "text-text-secondary hover:text-text-primary hover:bg-bg-primary"
                }`}
              >
                <UserRound size={14} /> Full Details
              </button>
              <button
                type="button"
                onClick={() => openEdit(selectedEmployee)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === "edit"
                    ? "bg-ai-50 text-ai-700 border border-ai-200"
                    : "text-text-secondary hover:text-text-primary hover:bg-bg-primary"
                }`}
              >
                <Pencil size={14} /> Edit Profile
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("allowances")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === "allowances"
                    ? "bg-ai-50 text-ai-700 border border-ai-200"
                    : "text-text-secondary hover:text-text-primary hover:bg-bg-primary"
                }`}
              >
                <Sparkles size={14} /> Allowances ({employeeAllowances.length})
              </button>
            </div>

            {/* TAB 1: FULL DETAILS */}
            {activeTab === "details" && (
              <div className="space-y-5">
                {/* Status overview bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl bg-bg-primary border border-border-subtle">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-ai-100 text-ai-700 font-bold flex items-center justify-center text-sm">
                      {selectedEmployee.full_name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="font-semibold text-text-primary text-base">
                        {selectedEmployee.full_name}
                      </div>
                      <div className="text-xs text-text-muted">
                        {[selectedEmployee.employee_code, selectedEmployee.designation, selectedEmployee.department]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <div className="text-xs text-text-muted">Monthly Basic</div>
                      <div className="text-sm font-bold text-text-primary">
                        {formatCurrency(selectedEmployee.basic_salary)}
                      </div>
                    </div>
                    <StatusBadge status={selectedEmployee.is_active ? selectedEmployee.status : "VOIDED"} />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Job & Organization */}
                  <div className="rounded-xl border border-border-subtle p-4 space-y-3 bg-bg-surface">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                      <Briefcase size={14} /> Employment & Role
                    </div>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Employee Code</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.employee_code || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Designation</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.designation || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Department</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.department || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Date of Joining</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.date_of_joining}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Employment Type</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.employment_type || "Regular / Permanent"}</span>
                      </div>
                      <div className="flex justify-between py-1">
                        <span className="text-text-secondary">Payroll Pay Day</span>
                        <span className="font-medium text-text-primary">
                          {selectedEmployee.pay_day ? `Day ${selectedEmployee.pay_day} of month` : "Month end"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Compensation & Bank Info */}
                  <div className="rounded-xl border border-border-subtle p-4 space-y-3 bg-bg-surface">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                      <CreditCard size={14} /> Compensation & Banking
                    </div>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Basic Monthly Salary</span>
                        <span className="font-semibold text-emerald-600">{formatCurrency(selectedEmployee.basic_salary)}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Bank Name</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.bank_name || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">Bank Account Number</span>
                        <span className="font-mono text-xs font-medium text-text-primary">{selectedEmployee.bank_account_number || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-border-subtle">
                        <span className="text-text-secondary">CNIC / National ID</span>
                        <span className="font-mono text-xs font-medium text-text-primary">{selectedEmployee.cnic || "—"}</span>
                      </div>
                      <div className="flex justify-between py-1">
                        <span className="text-text-secondary">Tax / NTN</span>
                        <span className="font-medium text-text-primary">{selectedEmployee.tax_number || "—"}</span>
                      </div>
                    </div>
                  </div>

                  {/* Contact & Personal */}
                  <div className="rounded-xl border border-border-subtle p-4 space-y-3 bg-bg-surface md:col-span-2">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                      <Phone size={14} /> Contact & Personal Details
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                      <div>
                        <div className="text-xs text-text-muted">Phone</div>
                        <div className="font-medium text-text-primary mt-0.5">{selectedEmployee.phone || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-text-muted">Email</div>
                        <div className="font-medium text-text-primary mt-0.5">{selectedEmployee.email || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-text-muted">Address</div>
                        <div className="font-medium text-text-primary mt-0.5">{selectedEmployee.address || "—"}</div>
                      </div>
                    </div>
                    {selectedEmployee.notes && (
                      <div className="pt-2 border-t border-border-subtle">
                        <div className="text-xs text-text-muted">Notes</div>
                        <div className="text-sm text-text-secondary mt-1">{selectedEmployee.notes}</div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => openEdit(selectedEmployee)}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
                  >
                    <Pencil size={15} /> Edit Employee
                  </button>
                </div>
              </div>
            )}

            {/* TAB 2: EDIT EMPLOYEE */}
            {activeTab === "edit" && (
              <div className="space-y-4">
                {editError && (
                  <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm flex items-center gap-2">
                    <AlertCircle size={16} className="shrink-0" />
                    <span>{editError}</span>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className={labelCls}>Full name *</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.full_name}
                      onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                      placeholder="e.g. Gulfam Haider"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Designation</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.designation}
                      onChange={(e) => setEditForm({ ...editForm, designation: e.target.value })}
                      placeholder="e.g. BD Intern, Software Engineer"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>Department</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.department}
                      onChange={(e) => setEditForm({ ...editForm, department: e.target.value })}
                      placeholder="e.g. Sales, Engineering"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Date of joining *</label>
                    <input
                      type="date"
                      className={`${inputCls} mt-1`}
                      value={editForm.date_of_joining}
                      onChange={(e) => setEditForm({ ...editForm, date_of_joining: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Basic salary (monthly) *</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.basic_salary}
                      onChange={(e) => setEditForm({ ...editForm, basic_salary: e.target.value })}
                      placeholder="e.g. 50,000"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>Employment type</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.employment_type}
                      onChange={(e) => setEditForm({ ...editForm, employment_type: e.target.value })}
                      placeholder="e.g. Permanent, Contract, Intern"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Status</label>
                    <select
                      className={`${inputCls} mt-1`}
                      value={editForm.status || "ACTIVE"}
                      onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                    >
                      <option value="ACTIVE">ACTIVE</option>
                      <option value="ON_LEAVE">ON_LEAVE</option>
                      <option value="PROBATION">PROBATION</option>
                      <option value="SUSPENDED">SUSPENDED</option>
                      <option value="TERMINATED">TERMINATED</option>
                    </select>
                  </div>
                  <div>
                    <label className={labelCls}>Pay day of month</label>
                    <input
                      type="number"
                      min={1}
                      max={31}
                      className={`${inputCls} mt-1`}
                      value={editForm.pay_day}
                      onChange={(e) => setEditForm({ ...editForm, pay_day: e.target.value })}
                      placeholder="1 - 31"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className={labelCls}>Phone</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.phone}
                      onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                      placeholder="e.g. +92 300 1234567"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Email</label>
                    <input
                      type="email"
                      className={`${inputCls} mt-1`}
                      value={editForm.email}
                      onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                      placeholder="e.g. gulfam@example.com"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>CNIC / National ID</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.cnic}
                      onChange={(e) => setEditForm({ ...editForm, cnic: e.target.value })}
                      placeholder="e.g. 35201-1234567-1"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Bank name</label>
                    <input
                      className={`${inputCls} mt-1`}
                      value={editForm.bank_name}
                      onChange={(e) => setEditForm({ ...editForm, bank_name: e.target.value })}
                      placeholder="e.g. Meezan Bank, HBL"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Bank account number / IBAN</label>
                    <input
                      className={`${inputCls} mt-1 font-mono`}
                      value={editForm.bank_account_number}
                      onChange={(e) => setEditForm({ ...editForm, bank_account_number: e.target.value })}
                      placeholder="e.g. 010203040506"
                    />
                  </div>
                </div>

                <div>
                  <label className={labelCls}>Notes</label>
                  <textarea
                    rows={2}
                    className={`${inputCls} mt-1`}
                    value={editForm.notes}
                    onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                    placeholder="Performance notes, emergency contact, or equipment allocated..."
                  />
                </div>

                <div className="flex items-center justify-end gap-3 pt-3 border-t border-border-subtle">
                  <button
                    type="button"
                    onClick={() => setActiveTab("details")}
                    className="px-4 py-2 rounded-xl border border-border-default bg-bg-surface text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={savingEdit}
                    onClick={handleUpdateEmployee}
                    className="px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
                  >
                    {savingEdit ? "Saving changes..." : "Save changes"}
                  </button>
                </div>
              </div>
            )}

            {/* TAB 3: ALLOWANCES & BENEFITS */}
            {activeTab === "allowances" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-text-primary">
                    Active Allowances & Benefits
                  </div>
                  <div className="text-xs text-text-muted">
                    Total Allowances: {employeeAllowances.length}
                  </div>
                </div>

                {loadingAllowances ? (
                  <div className="py-6 text-center text-sm text-text-muted">Loading allowances…</div>
                ) : employeeAllowances.length === 0 ? (
                  <div className="p-6 text-center border border-dashed border-border-subtle rounded-xl text-sm text-text-muted">
                    No additional allowances or benefits set for this employee yet.
                  </div>
                ) : (
                  <div className="divide-y divide-border-subtle border border-border-subtle rounded-xl overflow-hidden bg-bg-surface">
                    {employeeAllowances.map((a) => (
                      <div key={a.id} className="p-3.5 flex items-center justify-between text-sm">
                        <div>
                          <div className="font-medium text-text-primary">{a.description}</div>
                          <div className="text-xs text-text-muted">
                            {[a.allowance_type, a.frequency, a.source === "AI" ? "Configured by AI" : "Manual"]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="font-semibold text-emerald-600">+{formatCurrency(a.amount)}</div>
                          <div className="text-xs text-text-muted">{a.frequency}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* AI Allowance adder */}
                <div className="p-4 rounded-xl border border-ai-200 bg-ai-50/50 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-ai-700">
                    <Sparkles size={14} /> Add or Update Allowances with AI
                  </div>
                  <p className="text-xs text-text-secondary">
                    Describe allowances in natural language, for example:{" "}
                    <em>&ldquo;Add 15,000 monthly fuel allowance and 20,000 house rent&rdquo;</em>.
                  </p>
                  <div className="flex gap-2">
                    <input
                      className={inputCls}
                      value={allowanceText}
                      onChange={(e) => setAllowanceText(e.target.value)}
                      placeholder="e.g. 15,000 monthly medical allowance"
                    />
                    <button
                      type="button"
                      disabled={aiBusy || !allowanceText.trim()}
                      onClick={() => {
                        const txt = allowanceText.trim();
                        if (!txt) return;
                        setAllowanceText("");
                        setDetailsOpen(false);
                        if (selectedEmployee) {
                          void runAllowanceAi(selectedEmployee, txt);
                        }
                      }}
                      className="px-4 rounded-xl bg-ai-500 hover:bg-ai-600 disabled:opacity-50 text-white text-sm font-medium transition-colors shrink-0"
                    >
                      Apply
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Add Employee Modal */}
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
