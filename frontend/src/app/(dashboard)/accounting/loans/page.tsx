"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, Plus, X } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrg } from "@/lib/hooks/useOrg";
import { formatCurrency } from "@/lib/utils/currency";
import { aiClarify, aiConfirm, aiExecute } from "@/lib/api/client";
import PageHeader from "@/components/shared/PageHeader";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import StatusBadge from "@/components/shared/StatusBadge";
import { cn } from "@/lib/utils/cn";
import {
  currentNonCurrentSplit,
  num,
  outstandingPrincipal,
  type InstallmentRow,
  type LoanDirection,
  type LoanRow,
} from "@/lib/loans/logic";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

interface NewLoanForm {
  direction: LoanDirection;
  narration: string;
  counterparty: string;
  purpose: string;
  principal: string;
  loan_date: string;
  first_payment_date: string;
  tenure_months: string;
  frequency: string;
  interest_rate: string;
  interest_method: string;
  grace_months: string;
  balloon_amount: string;
}

const EMPTY_FORM: NewLoanForm = {
  direction: "BORROWED",
  narration: "",
  counterparty: "",
  purpose: "",
  principal: "",
  loan_date: new Date().toISOString().slice(0, 10),
  first_payment_date: "",
  tenure_months: "36",
  frequency: "MONTHLY",
  interest_rate: "12",
  interest_method: "REDUCING",
  grace_months: "0",
  balloon_amount: "0",
};

/** Build the chat message — carries EVERY schedule field so the first LLM
 * call can plan without clarification (spec: gather up front, never ask
 * "what account should I credit"). */
function loanMessage(f: NewLoanForm): string {
  return [
    `Record a new ${f.direction === "BORROWED" ? "borrowed loan" : "loan given"}.`,
    `Narration: ${f.narration}.`,
    f.direction === "BORROWED" ? `Lender: ${f.counterparty}.` : `Borrower: ${f.counterparty}.`,
    f.purpose ? `Purpose: ${f.purpose}.` : "",
    `Amount: ${f.principal}, loan date ${f.loan_date},`,
    `first repayment ${f.first_payment_date}, tenure ${f.tenure_months} months,`,
    `frequency ${f.frequency}, interest ${f.interest_rate}% per year,`,
    `method ${f.interest_method}.`,
    Number(f.grace_months) > 0 ? `Grace period ${f.grace_months} months.` : "",
    Number(f.balloon_amount) > 0 ? `Balloon payment ${f.balloon_amount}.` : "",
  ].filter(Boolean).join(" ");
}

type AgentStep = { status?: string; execution_id?: string; question?: string; summary?: string };

export default function LoansPage() {
  const { org, loading: orgLoading } = useOrg();
  const [loans, setLoans] = useState<LoanRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState<LoanDirection>("BORROWED");
  const [selected, setSelected] = useState<LoanRow | null>(null);
  const [schedule, setSchedule] = useState<InstallmentRow[] | null>(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);

  // New loan modal + AI conversation state
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<NewLoanForm>(EMPTY_FORM);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiQuestion, setAiQuestion] = useState<{ session_id: string; question: string } | null>(null);
  const [aiAnswer, setAiAnswer] = useState("");

  const load = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error: dbError } = await supabase
      .from("v_loans")
      .select("*")
      .eq("organization_id", org.organization_id)
      .order("created_at", { ascending: false });
    if (dbError) setError(dbError.message);
    else setLoans((data ?? []) as LoanRow[]);
  }, [org]);

  useEffect(() => { load(); }, [load]);

  const openSchedule = useCallback(async (loan: LoanRow) => {
    setSelected(loan);
    setSchedule(null);
    setScheduleLoading(true);
    const supabase = createClient();
    const { data } = await supabase
      .from("v_loan_installment_schedule")
      .select("*")
      .eq("loan_id", loan.id)
      .order("installment_no");
    setSchedule((data ?? []) as InstallmentRow[]);
    setScheduleLoading(false);
  }, []);

  const visible = useMemo(
    () => (loans ?? []).filter((l) => l.direction === direction),
    [loans, direction]
  );

  const summary = useMemo(() => {
    const active = visible.filter((l) => l.status === "ACTIVE");
    const outstanding = active.reduce(
      (s, l) => s + num(l.principal) - num(l.principal_paid), 0);
    const overdue = active.reduce((s, l) => s + num(l.overdue_count), 0);
    const nextDue = active
      .map((l) => String(l.next_due_date || ""))
      .filter(Boolean)
      .sort()[0] ?? "—";
    return { active: active.length, outstanding, overdue, nextDue };
  }, [visible]);

  /** Drive the AI pipeline: execute → (clarify)* → confirm → reload.
   * The backend owns ALL accounting logic; the page only gathers the
   * fields and relays them (spec: first call to LLM, then further). */
  const runThroughAgent = async (message: string) => {
    setAiBusy(true);
    setAiError(null);
    setAiQuestion(null);
    try {
      let step: AgentStep = await aiExecute({ message } as never);
      for (let i = 0; i < 5; i++) {
        if (step.status === "AWAITING_CLARIFICATION" && step.execution_id) {
          // Pause: surface the question to the operator instead of guessing.
          setAiQuestion({ session_id: step.execution_id, question: step.question || "Details needed" });
          setAiBusy(false);
          return;
        }
        if (step.status === "AWAITING_CONFIRMATION" && step.execution_id) {
          step = await aiConfirm({ session_id: step.execution_id, approved: true });
          continue;
        }
        break;
      }
      if (step.status === "COMPLETED") {
        setModalOpen(false);
        setForm(EMPTY_FORM);
        await load();
      } else {
        setAiError(step.summary || step.status || "The request did not complete.");
      }
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiBusy(false);
    }
  };

  const submitClarification = async () => {
    if (!aiQuestion || !aiAnswer.trim()) return;
    setAiBusy(true);
    setAiError(null);
    try {
      let step: AgentStep = await aiClarify({
        session_id: aiQuestion.session_id, answer: aiAnswer,
      });
      setAiQuestion(null);
      setAiAnswer("");
      for (let i = 0; i < 5; i++) {
        if (step.status === "AWAITING_CLARIFICATION" && step.execution_id) {
          setAiQuestion({ session_id: step.execution_id, question: step.question || "Details needed" });
          break;
        }
        if (step.status === "AWAITING_CONFIRMATION" && step.execution_id) {
          step = await aiConfirm({ session_id: step.execution_id, approved: true });
          continue;
        }
        break;
      }
      if (step.status === "COMPLETED") {
        setModalOpen(false);
        setForm(EMPTY_FORM);
        await load();
      } else if (step.status !== "AWAITING_CLARIFICATION") {
        setAiError(step.summary || step.status || "The request did not complete.");
      }
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiBusy(false);
    }
  };


  const currency = org?.base_currency_code;

  // The current/non-current split is DERIVED from the schedule at render
  // time — it moves automatically as installments get paid or dates pass.
  const derived = useMemo(() => {
    if (!selected || !schedule) return null;
    const { current, nonCurrent } = currentNonCurrentSplit(schedule);
    return {
      outstanding: outstandingPrincipal(selected, schedule),
      current,
      nonCurrent,
    };
  }, [selected, schedule]);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Loans & Financing"
        subtitle="Borrowings and lendings with full repayment schedules — the schedule is the source of truth for principal, interest and current/non-current classification"
        logoUrl={org?.logo_url}
        actions={
          <button
            onClick={() => { setForm(EMPTY_FORM); setAiError(null); setAiQuestion(null); setModalOpen(true); }}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> New Loan
          </button>
        }
      />

      {/* Direction tabs */}
      <div className="flex gap-2">
        {(["BORROWED", "GIVEN"] as LoanDirection[]).map((d) => (
          <button
            key={d}
            onClick={() => setDirection(d)}
            className={cn(
              "px-4 py-2 rounded-xl text-sm font-medium border transition-colors",
              direction === d
                ? "bg-bg-muted border-ai-300 text-text-primary"
                : "bg-bg-surface border-border-subtle text-text-muted hover:text-text-primary"
            )}
          >
            {d === "BORROWED" ? "Borrowed Loans" : "Loans / Advances Given"}
          </button>
        ))}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Active loans", value: String(summary.active) },
          { label: "Outstanding principal", value: formatCurrency(summary.outstanding, currency) },
          { label: "Next due", value: summary.nextDue },
          { label: "Overdue installments", value: String(summary.overdue) },
        ].map((c) => (
          <div key={c.label} className="bg-bg-surface rounded-2xl border border-border-subtle p-4">
            <p className="text-xs text-text-muted">{c.label}</p>
            <p className={cn("mt-1 text-lg font-semibold tabular-nums text-text-primary",
              c.label === "Overdue installments" && summary.overdue > 0 && "text-error-700")}>
              {c.value}
            </p>
          </div>
        ))}
      </div>

      {orgLoading || (!loans && !error) ? (
        <TableSkeleton rows={6} cols={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={direction === "BORROWED" ? "No borrowed loans yet" : "No loans given yet"}
          hint="Record one with the AI agent or the New Loan button — terms, schedule and the initial journal are created together."
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-bg-muted/60 text-left text-xs text-text-muted">
                <th className="px-4 py-2.5">Loan / Narration</th>
                <th className="px-4 py-2.5">{direction === "BORROWED" ? "Lender" : "Borrower"}</th>
                <th className="px-4 py-2.5 text-right">Principal</th>
                <th className="px-4 py-2.5 text-right">Outstanding</th>
                <th className="px-4 py-2.5 text-right">Current (12m)</th>
                <th className="px-4 py-2.5 text-right">Non-Current</th>
                <th className="px-4 py-2.5">Next due</th>
                <th className="px-4 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((l) => (
                  <tr key={l.id}
                    onClick={() => openSchedule(l)}
                    className={cn("border-b border-border-subtle/60 last:border-0 cursor-pointer hover:bg-bg-muted/40",
                      selected?.id === l.id && "bg-bg-muted/60")}>
                    <td className="px-4 py-2.5 font-medium text-text-primary">{l.narration}</td>
                    <td className="px-4 py-2.5 text-text-secondary">{l.counterparty}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{formatCurrency(num(l.principal), currency)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCurrency(num(l.principal) - num(l.principal_paid), currency)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCurrency(num(l.current_portion), currency)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCurrency(num(l.noncurrent_portion), currency)}
                    </td>
                    <td className="px-4 py-2.5 text-text-secondary">{String(l.next_due_date || "—")}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={l.status} /></td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}


      {/* Schedule detail panel */}
      {selected && (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
          <div className="px-4 py-3 bg-bg-muted/60 border-b border-border-subtle flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CalendarClock className="w-4 h-4 text-text-muted" />
              <h2 className="text-sm font-semibold text-text-primary">
                Repayment Schedule — {selected.narration}
              </h2>
            </div>
            <button onClick={() => setSelected(null)} className="text-text-muted hover:text-text-primary">
              <X className="w-4 h-4" />
            </button>
          </div>
          {derived && (
            <div className="px-4 py-2.5 border-b border-border-subtle bg-bg-muted/30 flex flex-wrap gap-x-6 text-xs">
              <span className="text-text-muted">
                Outstanding: <span className="font-semibold text-text-primary tabular-nums">
                  {formatCurrency(derived.outstanding, currency)}</span>
              </span>
              <span className="text-text-muted">
                Current portion (next 12 months): <span className="font-semibold text-text-primary tabular-nums">
                  {formatCurrency(derived.current, currency)}</span>
              </span>
              <span className="text-text-muted">
                Non-current portion: <span className="font-semibold text-text-primary tabular-nums">
                  {formatCurrency(derived.nonCurrent, currency)}</span>
              </span>
            </div>
          )}
          {scheduleLoading ? (
            <TableSkeleton rows={6} cols={7} />
          ) : !schedule || schedule.length === 0 ? (
            <p className="px-4 py-4 text-text-muted text-xs">No installments.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg-muted/40 text-left text-xs text-text-muted">
                  <th className="px-4 py-2">#</th>
                  <th className="px-4 py-2">Due date</th>
                  <th className="px-4 py-2 text-right">Opening</th>
                  <th className="px-4 py-2 text-right">Principal</th>
                  <th className="px-4 py-2 text-right">Interest</th>
                  <th className="px-4 py-2 text-right">Total payment</th>
                  <th className="px-4 py-2 text-right">Closing</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {schedule.map((r) => {
                  const st = String(r.live_status ?? r.status ?? "");
                  const unpaid = !["PAID", "WAIVED"].includes(st);
                  return (
                    <tr key={r.installment_no} className="border-b border-border-subtle/60 last:border-0">
                      <td className="px-4 py-2 tabular-nums text-text-secondary">{r.installment_no}</td>
                      <td className="px-4 py-2">{r.due_date}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatCurrency(num(r.opening_principal), currency)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatCurrency(num(r.principal_component), currency)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatCurrency(num(r.interest_component), currency)}</td>
                      <td className="px-4 py-2 text-right tabular-nums font-medium">{formatCurrency(num(r.total_due), currency)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatCurrency(num(r.closing_principal), currency)}</td>
                      <td className="px-4 py-2">
                        <span className={cn("text-xs px-2 py-0.5 rounded-lg border",
                          st === "OVERDUE" ? "border-error-200 text-error-700 bg-error-50"
                            : st === "PAID" ? "border-success-200 text-success-700 bg-success-50"
                            : st === "DUE" ? "border-ai-300 text-ai-700 bg-ai-50"
                            : "border-border-subtle text-text-muted")}>
                          {st}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">
                        {unpaid && (
                          <button
                            onClick={() => runThroughAgent(
                              `Record loan installment #${r.installment_no} payment of ${num(r.total_due)} for loan '${selected.narration}' dated ${new Date().toISOString().slice(0, 10)}.`
                            )}
                            disabled={aiBusy}
                            className="px-3 py-1 rounded-lg text-xs font-medium bg-bg-muted border border-border-subtle hover:border-ai-300 disabled:opacity-40 transition-colors"
                          >
                            Record payment
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}


      {aiError && (
        <p className="text-xs text-error-600 bg-error-50 border border-error-200 rounded-xl px-3 py-2">
          {aiError}
        </p>
      )}

      {/* New Loan modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => !aiBusy && setModalOpen(false)}>
          <div className="bg-bg-surface rounded-2xl border border-border-subtle w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold text-text-primary">New Loan</h2>

            {aiQuestion ? (
              <div className="space-y-3">
                <p className="text-sm text-text-secondary bg-bg-muted rounded-xl px-3 py-2 border border-border-subtle">
                  {aiQuestion.question}
                </p>
                <textarea className={`${inputCls} h-20`} value={aiAnswer}
                  onChange={(e) => setAiAnswer(e.target.value)}
                  placeholder="Your answer…" />
                <div className="flex justify-end gap-2">
                  <button onClick={() => setModalOpen(false)}
                    className="px-4 py-2 rounded-xl text-sm text-text-secondary hover:text-text-primary">Cancel</button>
                  <button onClick={submitClarification} disabled={aiBusy || !aiAnswer.trim()}
                    className="px-5 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40">
                    {aiBusy ? "Working…" : "Answer"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Direction *</label>
                    <select className={`${inputCls} mt-1.5`} value={form.direction}
                      onChange={(e) => setForm({ ...form, direction: e.target.value as LoanDirection })}>
                      <option value="BORROWED">Borrowed (received)</option>
                      <option value="GIVEN">Given (lent out)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">
                      {form.direction === "BORROWED" ? "Lender *" : "Borrower *"}
                    </label>
                    <input className={`${inputCls} mt-1.5`} value={form.counterparty}
                      onChange={(e) => setForm({ ...form, counterparty: e.target.value })}
                      placeholder={form.direction === "BORROWED" ? "e.g. HBL" : "e.g. ABC Trading"} />
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-text-secondary">Unique loan narration *</label>
                  <input className={`${inputCls} mt-1.5`} value={form.narration}
                    onChange={(e) => setForm({ ...form, narration: e.target.value })}
                    placeholder={`Loan - ${form.counterparty || "Lender"} - ${form.direction === "BORROWED" ? "Facility" : "Advance"} - ${new Date().getFullYear()}`} />
                  <p className="text-[11px] text-text-muted mt-1">
                    Stays attached to every journal this loan generates.
                  </p>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Amount *</label>
                    <input className={`${inputCls} mt-1.5`} value={form.principal}
                      onChange={(e) => setForm({ ...form, principal: e.target.value })}
                      placeholder="1200000" inputMode="decimal" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Loan date</label>
                    <input type="date" className={`${inputCls} mt-1.5`} value={form.loan_date}
                      onChange={(e) => setForm({ ...form, loan_date: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Purpose</label>
                    <input className={`${inputCls} mt-1.5`} value={form.purpose}
                      onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                      placeholder="Vehicle Financing" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-3">
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Tenure (months) *</label>
                    <input className={`${inputCls} mt-1.5`} value={form.tenure_months}
                      onChange={(e) => setForm({ ...form, tenure_months: e.target.value })}
                      inputMode="numeric" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Frequency *</label>
                    <select className={`${inputCls} mt-1.5`} value={form.frequency}
                      onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
                      {["MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUALLY"].map((f) => (
                        <option key={f} value={f}>{f.replace("_", "-").toLowerCase()}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Interest % p.a.</label>
                    <input className={`${inputCls} mt-1.5`} value={form.interest_rate}
                      onChange={(e) => setForm({ ...form, interest_rate: e.target.value })}
                      inputMode="decimal" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Method</label>
                    <select className={`${inputCls} mt-1.5`} value={form.interest_method}
                      onChange={(e) => setForm({ ...form, interest_method: e.target.value })}>
                      <option value="REDUCING">Reducing</option>
                      <option value="FLAT">Flat</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs font-medium text-text-secondary">First repayment *</label>
                    <input type="date" className={`${inputCls} mt-1.5`} value={form.first_payment_date}
                      onChange={(e) => setForm({ ...form, first_payment_date: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Grace (months)</label>
                    <input className={`${inputCls} mt-1.5`} value={form.grace_months}
                      onChange={(e) => setForm({ ...form, grace_months: e.target.value })}
                      inputMode="numeric" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-text-secondary">Balloon</label>
                    <input className={`${inputCls} mt-1.5`} value={form.balloon_amount}
                      onChange={(e) => setForm({ ...form, balloon_amount: e.target.value })}
                      inputMode="decimal" />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-1">
                  <button onClick={() => setModalOpen(false)} disabled={aiBusy}
                    className="px-4 py-2 rounded-xl text-sm text-text-secondary hover:text-text-primary disabled:opacity-40">
                    Cancel
                  </button>
                  <button
                    onClick={() => runThroughAgent(loanMessage(form))}
                    disabled={aiBusy || !form.narration.trim() || !form.counterparty.trim()
                      || !form.principal.trim() || !form.first_payment_date}
                    className="px-5 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed">
                    {aiBusy ? "Recording…" : "Create via AI"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

