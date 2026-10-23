"use client";

import React from "react";
import { LayoutDashboard, FileText, Printer } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export interface ReportViewToggleProps {
  viewMode: "screen" | "document";
  onViewModeChange: (mode: "screen" | "document") => void;
  onPrint?: () => void;
}

export default function ReportViewToggle({
  viewMode,
  onViewModeChange,
  onPrint,
}: ReportViewToggleProps) {
  const handlePrint = () => {
    if (onPrint) {
      onPrint();
    } else {
      window.print();
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 print:hidden">
      {/* Switcher */}
      <div className="flex items-center rounded-xl bg-bg-surface border border-border-subtle p-0.5 shadow-sm">
        <button
          type="button"
          onClick={() => onViewModeChange("screen")}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
            viewMode === "screen"
              ? "bg-ai-600 text-white shadow-sm"
              : "text-text-secondary hover:text-text-primary"
          )}
          title="Interactive screen view with dashboard cards and metrics"
        >
          <LayoutDashboard className="w-3.5 h-3.5" />
          <span>Screen View</span>
        </button>

        <button
          type="button"
          onClick={() => onViewModeChange("document")}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
            viewMode === "document"
              ? "bg-ai-600 text-white shadow-sm"
              : "text-text-secondary hover:text-text-primary"
          )}
          title="Formal financial document layout with letterhead and A4 formatting"
        >
          <FileText className="w-3.5 h-3.5" />
          <span>Document Layout</span>
        </button>
      </div>

      {/* Print / Export Button */}
      <button
        type="button"
        onClick={handlePrint}
        className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-bg-surface border border-border-subtle text-xs font-semibold text-text-secondary hover:text-text-primary hover:border-ai-300 hover:bg-slate-50 transition-all shadow-sm"
        title="Print or export multi-page PDF"
      >
        <Printer className="w-3.5 h-3.5 text-ai-700" />
        <span>Print / PDF</span>
      </button>
    </div>
  );
}

