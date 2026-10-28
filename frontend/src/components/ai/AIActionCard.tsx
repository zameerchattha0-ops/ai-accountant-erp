"use client";

import Link from "next/link";
import { CheckCircle2, ExternalLink, BookOpen, Info, XCircle, RotateCcw, ArrowRight } from "lucide-react";
import type { AgentResponse } from "@/lib/types/api";
import { formatCurrency } from "@/lib/utils/currency";
import { cn } from "@/lib/utils/cn";
import { mdToDisplayText } from "@/lib/ai/markdown";

interface Props {
  response: AgentResponse;
}

// canonical nature values are rendered as readable labels
// (plain hyphens only - never em/en dashes).
const NATURE_LABELS: Record<string, string> = {
  FIXED_ASSET: "Fixed Asset",
  INVENTORY: "Inventory",
  CONSUMABLE: "Consumable",
  OPERATING_EXPENSE: "Operating Expense",
  SERVICE: "Service",
  GOODS: "Goods",
  ASSET_DISPOSAL: "Fixed Asset Disposal",
  OTHER_INCOME: "Other Income",
  PREPAID_EXPENSE: "Prepaid Expense",
  OWNER_DRAWING: "Owner Drawing",
  ALLOCATION: "Against Invoice/Bill",
  ADVANCE: "Advance",
  LOAN_OR_SETTLEMENT: "Loan or Settlement",
  RETURN_OF_GOODS: "Return of Goods",
  PRICE_ADJUSTMENT: "Price Adjustment",
  SERVICE_REVERSAL: "Service Reversal",
};

function natureLabel(nature: unknown): string {
  const key = typeof nature === "string" ? nature : "";
  if (NATURE_LABELS[key]) return NATURE_LABELS[key];
  return key ? key.replace(/_/g, " ").toLowerCase() : String(nature);
}

/* ---- View Details target -------------------------------------------------
   Maps the action/intent that produced this card to the page where the
   recorded transaction actually lives. Only /sales/invoices/[id] has a
   DETAIL route today, so that one deep-links to the exact record via the
   affected entity's id; every other action links to its module page.
---------------------------------------------------------------------------*/
const ENTITY_DETAIL_ROUTES: Record<string, string> = {
  invoice: "/sales/invoices",
  quotation: "/sales/quotations",
};

const ACTION_ROUTES: Record<string, string> = {
  create_invoice: "/sales/invoices",
  // CASH sale/purchase create NO invoice/bill document — they post a direct
  // journal (Dr/Cr Cash-or-Bank).  Their record IS the journal entry, so they
  // link to the Journal page (which drill-throughs to the GL/COA), never to a
  // payable/receivable document page that does not exist for them.
  record_cash_sale: "/accounting/journal",
  record_credit_sale: "/sales/invoices",
  create_quotation: "/sales/quotations",
  create_credit_note: "/sales/credit-notes",
  record_credit_purchase: "/purchases/bills",
  record_cash_purchase: "/accounting/journal",
  create_purchase_return: "/purchases/returns",
  record_expense: "/expenses",
  record_payment: "/payments",
  record_receipt: "/receipts",
  record_bank_transfer: "/banking",
  register_fixed_asset: "/accounting/journal",
  dispose_fixed_asset: "/accounting/journal",
  record_asset_depreciation: "/accounting/journal",
  generate_trial_balance: "/accounting/trial-balance",
  generate_profit_loss: "/reports/profit-loss",
  generate_balance_sheet: "/reports/balance-sheet",
  generate_cash_flow: "/reports/cash-flow",
  customer_balance: "/customers",
  supplier_balance: "/suppliers",
};

function detailsTarget(response: AgentResponse): string | null {
  // Deep-link to the exact record when the affected entity carries an id
  // AND a detail page exists for its type (e.g. invoice -> /sales/invoices/<id>).
  const entity = response.affected_entities?.find(
    (e) => {
      const base = e.type ? ENTITY_DETAIL_ROUTES[e.type.toLowerCase()] : undefined;
      return base && e.id;
    }
  );
  if (entity) {
    return `${ENTITY_DETAIL_ROUTES[entity.type.toLowerCase()]}/${entity.id}`;
  }
  // Otherwise the module page for the recorded action...
  if (response.action && ACTION_ROUTES[response.action]) {
    return ACTION_ROUTES[response.action];
  }
  // ...or the AI Activity trail for unmapped actions.
  return response.execution_id ? "/ai-activity" : null;
}

export default function AIActionCard({ response }: Props) {
  // VERIFIED means the ERP operation actually executed and its resulting
  // DB state was verified.  A text-only AI answer (no tools executed) is
  // UNVERIFIED - an AI response is NOT a completed ERP operation.
  const verification = response.verification_status;
  const isVerified = verification === "VERIFIED";
  const isUnverified = verification === "UNVERIFIED";
  const target = detailsTarget(response);

  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle shadow-sm overflow-hidden">
      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-2.5 px-5 py-4 border-b border-border-subtle",
          isVerified ? "bg-success-50/50" : isUnverified ? "bg-bg-muted/50" : "bg-error-50/50"
        )}
      >
        {isUnverified ? (
          <Info className="w-5 h-5 text-text-secondary shrink-0" />
        ) : (
          <CheckCircle2
            className={cn("w-5 h-5 shrink-0", isVerified ? "text-success-600" : "text-error-600")}
          />
        )}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-text-primary">
              {isUnverified ? "AI Response" : actionLabel(response.action)}
            </h3>
            {verification && (
              <span
                className={cn(
                  "text-[11px] font-medium px-2 py-0.5 rounded-full border",
                  isVerified && "bg-success-50 text-success-700 border-success-100",
                  isUnverified && "bg-bg-muted text-text-secondary border-border-subtle",
                  !isVerified && !isUnverified && "bg-error-50 text-error-600 border-error-100"
                )}
              >
                {verification}
              </span>
            )}
            {/* the recorded transaction date is always shown
                prominently; an assumed-today default is labelled honestly. */}
            {typeof response.data?.transaction_date === "string" && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border bg-bg-muted text-text-secondary border-border-subtle">
                Dated: {response.data.transaction_date}
                {response.data.date_defaulted ? " (assumed today)" : ""}
              </span>
            )}
            {/* the resolved transaction nature is always
                shown next to the date so the accounting treatment is
                auditable ("you confirmed" = explicit user answer). */}
            {typeof response.data?.transaction_nature === "string" && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border bg-bg-muted text-text-secondary border-border-subtle">
                Nature: {natureLabel(response.data.transaction_nature)}
                {String(response.data.transaction_nature_source) === "USER_ANSWER"
                  ? " - you confirmed"
                  : ""}
              </span>
            )}
          </div>
          {response.summary && (
            /* R3.4a cousin: the analytics card's summary is authored as
               Markdown (`**`, backticks, `_`, pipe tables) but this <p> has no
               markdown engine — the raw markers were reaching the user
               ("**Loss: …**").  Render the known subset to clean text; plain
               summaries pass through untouched. */
            <p className="text-xs text-text-secondary mt-0.5 whitespace-pre-line">
              {mdToDisplayText(response.summary)}
            </p>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Audit Verification Table for Document Status Updates */}
        {(() => {
          const rawData = response.data as Record<string, any> | undefined;
          const auditDocs = Array.isArray(rawData?.documents) ? (rawData?.documents as any[]) : null;
          if (!auditDocs || auditDocs.length === 0) return null;
          return (
            <div className="space-y-2.5">
              <h4 className="text-xs font-semibold text-text-primary uppercase tracking-wide flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-success-600" /> Document Verification Table
              </h4>
              <div className="overflow-x-auto rounded-xl border border-border-subtle bg-bg-muted/40">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="border-b border-border-subtle bg-bg-muted text-text-muted font-medium">
                      <th className="px-3 py-2">Document Ref</th>
                      <th className="px-3 py-2">Party / Name</th>
                      <th className="px-3 py-2">Previous Status</th>
                      <th className="px-3 py-2">New Status</th>
                      <th className="px-3 py-2 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {auditDocs.map((doc: any, i: number) => (
                      <tr key={i} className="hover:bg-bg-muted/60 transition-colors">
                        <td className="px-3 py-2 font-mono font-medium">
                          {doc.url ? (
                            <Link href={doc.url} className="text-ai-600 hover:underline">
                              {String(doc.reference || "")}
                            </Link>
                          ) : (
                            <span>{String(doc.reference || "")}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-text-secondary">{String(doc.party_name || "—")}</td>
                        <td className="px-3 py-2">
                          <span className="px-1.5 py-0.5 rounded bg-bg-muted text-text-muted border border-border-subtle font-mono text-[10px]">
                            {String(doc.previous_status || "")}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <span className="px-1.5 py-0.5 rounded bg-success-50 text-success-700 border border-success-200 font-mono text-[10px] font-semibold">
                            {String(doc.new_status || "")}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right font-medium tabular-nums text-text-primary">
                          {doc.total != null && Number(doc.total) > 0 ? formatCurrency(Number(doc.total)) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center gap-2 pt-1">
                {auditDocs[0]?.url && (
                  <Link
                    href={auditDocs[0].url}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ai-50 text-ai-700 hover:bg-ai-100 text-xs font-medium transition-colors border border-ai-200"
                  >
                    <ExternalLink className="w-3 h-3" /> View Updated Documents
                  </Link>
                )}
                {rawData?.undo_available && (
                  <button
                    type="button"
                    onClick={() => {
                      alert(`To revert these changes, you can ask in chat: "Revert ${auditDocs.map((d: any) => d.reference).join(', ')} back to ${auditDocs[0]?.previous_status}".`);
                    }}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-bg-muted text-text-secondary hover:text-text-primary text-xs font-medium transition-colors border border-border-default"
                  >
                    <RotateCcw className="w-3 h-3" /> Undo / Revert
                  </button>
                )}
              </div>
            </div>
          );
        })()}

        {/* Affected Entities */}
        {response.affected_entities && response.affected_entities.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide">
              Details
            </h4>
            <div className="space-y-1.5">
              {response.affected_entities.map((entity, i) => {
                // Defensive: the backend contract guarantees a string `type`,
                // but never crash on malformed/missing/null values.
                const typeLabel = (entity?.type ?? "")
                  .toString()
                  .replace(/_/g, " ")
                  .trim() || "item";
                const detailLabel =
                  entity?.name || entity?.number || entity?.action || entity?.id || "";
                return (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span className="text-text-secondary capitalize">{typeLabel}</span>
                    <span className="text-text-primary font-medium">
                      {detailLabel}
                      {entity?.total != null && (
                        <span className="ml-2 tabular-nums">{formatCurrency(entity.total)}</span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Accounting Impact */}
        {response.accounting_impact && response.accounting_impact.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide flex items-center gap-1.5">
              <BookOpen className="w-3.5 h-3.5" /> Accounting Entry
            </h4>
            <div className="bg-bg-muted rounded-xl p-3 space-y-1">
              {response.accounting_impact.map((entry, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">{entry.account}</span>
                  <span className="text-text-primary font-medium tabular-nums">
                    {entry.debit != null && (
                      <span>Dr {formatCurrency(entry.debit)}</span>
                    )}
                    {entry.credit != null && (
                      <span>Cr {formatCurrency(entry.credit)}</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Verification */}
        {verification && (
          <div
            className={cn(
              "flex items-center gap-2 text-xs",
              isVerified && "text-success-600",
              isUnverified && "text-text-muted",
              !isVerified && !isUnverified && "text-error-600"
            )}
          >
            {isVerified ? (
              <CheckCircle2 className="w-3.5 h-3.5" />
            ) : isUnverified ? (
              <Info className="w-3.5 h-3.5" />
            ) : (
              <XCircle className="w-3.5 h-3.5" />
            )}
            {isVerified
              ? "Verified - the resulting database state was checked."
              : isUnverified
                ? "Informational response - no ERP data was changed."
                : "Verification failed."}
          </div>
        )}

        {/* Action Links */}
        <div className="flex gap-2 pt-1">
          {target && (
            <Link
              href={target}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-muted text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            >
              <ExternalLink className="w-3 h-3" /> View Details
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function actionLabel(action?: string): string {
  if (!action) return "Completed";
  const labels: Record<string, string> = {
    record_credit_purchase: "Purchase Recorded",
    record_cash_purchase: "Purchase Recorded",
    update_document_status: "Document Status Updated",
    record_credit_sale: "Sale Recorded",
    record_cash_sale: "Sale Recorded",
    create_invoice: "Invoice Created",
    record_expense: "Expense Recorded",
    record_receipt: "Receipt Recorded",
    record_payment: "Payment Recorded",
    create_quotation: "Quotation Created",
    create_credit_note: "Credit Note Created",
    create_purchase_return: "Purchase Return Created",
    generate_trial_balance: "Trial Balance",
    generate_balance_sheet: "Balance Sheet",
    generate_profit_loss: "Profit & Loss",
    generate_cash_flow: "Cash Flow Statement",
    customer_balance: "Customer Balances",
    supplier_balance: "Supplier Balances",
  };
  return labels[action] || "Completed";
}
