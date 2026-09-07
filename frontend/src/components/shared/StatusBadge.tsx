import { cn } from "@/lib/utils/cn";

const STATUS_STYLES: Record<string, string> = {
  DRAFT: "bg-bg-muted text-text-secondary",
  ISSUED: "bg-info-50 text-info-700",
  CONFIRMED: "bg-info-50 text-info-700",
  POSTED: "bg-ai-50 text-ai-700",
  PAID: "bg-success-50 text-success-700",
  PARTIAL: "bg-warning-50 text-warning-700",
  PARTIALLY_PAID: "bg-warning-50 text-warning-700",
  OVERDUE: "bg-error-50 text-error-700",
  VOIDED: "bg-bg-muted text-text-muted line-through",
  CREDITED: "bg-ai-50 text-ai-700",
  OPEN: "bg-info-50 text-info-700",
  REVERSED: "bg-bg-muted text-text-muted",
  VALIDATED: "bg-info-50 text-info-700",
  COMPLETED: "bg-success-50 text-success-700",
  PENDING: "bg-warning-50 text-warning-700",
  CANCELLED: "bg-bg-muted text-text-muted line-through",
  SENT: "bg-info-50 text-info-700",
  ACCEPTED: "bg-success-50 text-success-700",
  REJECTED: "bg-error-50 text-error-700",
  EXPIRED: "bg-bg-muted text-text-muted",
  CONVERTED: "bg-ai-50 text-ai-700",
  CLOSED: "bg-bg-muted text-text-muted",
  LOCKED: "bg-bg-muted text-text-muted",
  ACTIVE: "bg-success-50 text-success-700",
  SUSPENDED: "bg-warning-50 text-warning-700",
  REMOVED: "bg-bg-muted text-text-muted",
  INVITED: "bg-warning-50 text-warning-700",
  ASSET: "bg-info-50 text-info-700",
  LIABILITY: "bg-warning-50 text-warning-700",
  EQUITY: "bg-ai-50 text-ai-700",
  REVENUE: "bg-success-50 text-success-700",
  EXPENSE: "bg-error-50 text-error-700",
};

const LABELS: Record<string, string> = {
  PARTIAL: "Partially Paid",
  PARTIALLY_PAID: "Partially Paid",
  CREDITED: "Credited",
};

export default function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-bg-muted text-text-secondary";
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium tracking-wide",
        style
      )}
    >
      {LABELS[status] ?? status}
    </span>
  );
}
