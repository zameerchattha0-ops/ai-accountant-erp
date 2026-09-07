"use client";

import { CheckCircle2, ExternalLink, BookOpen, Info, XCircle } from "lucide-react";
import type { AgentResponse } from "@/lib/types/api";
import { formatCurrency } from "@/lib/utils/currency";
import { cn } from "@/lib/utils/cn";

interface Props {
  response: AgentResponse;
}

// Work Stream R: canonical nature values are rendered as readable labels
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

export default function AIActionCard({ response }: Props) {
  // VERIFIED means the ERP operation actually executed and its resulting
  // DB state was verified.  A text-only AI answer (no tools executed) is
  // UNVERIFIED - an AI response is NOT a completed ERP operation.
  const verification = response.verification_status;
  const isVerified = verification === "VERIFIED";
  const isUnverified = verification === "UNVERIFIED";

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
            {/* Work Stream A: the recorded transaction date is always shown
                prominently; an assumed-today default is labelled honestly. */}
            {typeof response.data?.transaction_date === "string" && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border bg-bg-muted text-text-secondary border-border-subtle">
                Dated: {response.data.transaction_date}
                {response.data.date_defaulted ? " (assumed today)" : ""}
              </span>
            )}
            {/* Work Stream R: the resolved transaction nature is always
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
            <p className="text-xs text-text-secondary mt-0.5 whitespace-pre-line">{response.summary}</p>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
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
          {response.data && (
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-muted text-xs font-medium text-text-secondary hover:text-text-primary transition-colors">
              <ExternalLink className="w-3 h-3" /> View Details
            </button>
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
