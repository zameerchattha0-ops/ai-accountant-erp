"use client";

/**
 * Pagination — calm, keyboard-accessible page controls for server-paged lists.
 *
 * Enterprise pattern (not infinite scroll): predictable position, an explicit
 * "where am I" range, and hard-bounded rendering regardless of table size (§5).
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { pageRange, rangeLabel } from "@/lib/lists/logic";

interface PaginationProps {
  page: number;
  pageSize: number;
  count: number;
  onPageChange: (page: number) => void;
  /** Dim the controls while the next page loads (rows stay visible). */
  refreshing?: boolean;
}

export default function Pagination({
  page,
  pageSize,
  count,
  onPageChange,
  refreshing = false,
}: PaginationProps) {
  const range = pageRange(page, pageSize, count);
  // Single page (or empty): the range label alone reads cleaner than nav chrome.
  if (range.totalPages <= 1) {
    if (range.total === 0) return null;
    return (
      <p className="px-1 pt-1 text-xs text-text-muted tabular-nums">
        {rangeLabel(range)}
      </p>
    );
  }

  const btnCls =
    "inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-border-subtle bg-bg-surface text-xs font-medium text-text-secondary hover:text-text-primary hover:border-border-default disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ai-200 transition-colors";

  return (
    <nav
      aria-label="Pagination"
      className={`flex flex-wrap items-center justify-between gap-2 px-1 pt-1 transition-opacity ${
        refreshing ? "opacity-60" : "opacity-100"
      }`}
    >
      <p className="text-xs text-text-muted tabular-nums" aria-live="polite">
        {rangeLabel(range)}
      </p>
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-secondary tabular-nums">
          Page {range.from > 0 ? Math.floor(range.from / pageSize) + 1 : 1} of{" "}
          {range.totalPages}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className={btnCls}
            disabled={!range.hasPrev || refreshing}
            onClick={() => onPageChange(Math.max(0, page - 1))}
            aria-label="Previous page"
          >
            <ChevronLeft className="w-3.5 h-3.5" /> Prev
          </button>
          <button
            type="button"
            className={btnCls}
            disabled={!range.hasNext || refreshing}
            onClick={() => onPageChange(page + 1)}
            aria-label="Next page"
          >
            Next <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </nav>
  );
}
