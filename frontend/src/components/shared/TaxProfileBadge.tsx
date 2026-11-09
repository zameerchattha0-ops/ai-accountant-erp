"use client";

import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils/cn";

interface Props {
  status?: string | null;
  strn?: string | null;
  taxNumber?: string | null;
  onClick?: () => void;
  className?: string;
  showDetails?: boolean;
}

export default function TaxProfileBadge({
  status,
  strn,
  taxNumber,
  onClick,
  className,
  showDetails = true,
}: Props) {
  const normStatus = String(status || "").trim().toUpperCase();
  const isActive = normStatus.includes("ACTIVE") || normStatus.includes("ATL");
  const isInactive = normStatus.includes("INACTIVE") || normStatus.includes("SUSPENDED");
  const idValue = strn || taxNumber;

  if (isActive) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={!onClick}
        title={idValue ? `Active on FBR/Provincial ATL (STRN/NTN: ${idValue})` : "Active Taxpayer on FBR ATL"}
        className={cn(
          "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors border",
          "bg-emerald-50 text-emerald-700 border-emerald-200/80 hover:bg-emerald-100/80 shadow-2xs",
          onClick ? "cursor-pointer" : "cursor-default",
          className
        )}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
        <span className="font-semibold">Active ATL</span>
        {showDetails && idValue && (
          <span className="text-[10px] text-emerald-600/80 font-mono">
            · {idValue.length > 12 ? `${idValue.slice(0, 10)}…` : idValue}
          </span>
        )}
      </button>
    );
  }

  if (isInactive) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={!onClick}
        title={idValue ? `Inactive/Suspended on ATL (STRN/NTN: ${idValue})` : "Inactive on ATL"}
        className={cn(
          "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors border",
          "bg-amber-50 text-amber-700 border-amber-200/80 hover:bg-amber-100/80",
          onClick ? "cursor-pointer" : "cursor-default",
          className
        )}
      >
        <AlertCircle className="w-3 h-3 text-amber-500 shrink-0" />
        <span>Inactive</span>
        {showDetails && idValue && (
          <span className="text-[10px] text-amber-600/80 font-mono">
            · {idValue.slice(0, 8)}
          </span>
        )}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      title="Unregistered for Sales Tax / GST"
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors border",
        "bg-bg-muted/70 text-text-muted border-border-subtle hover:bg-bg-muted",
        onClick ? "cursor-pointer" : "cursor-default",
        className
      )}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0" />
      <span>Unregistered</span>
    </button>
  );
}

