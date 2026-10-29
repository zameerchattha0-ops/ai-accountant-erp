import React from "react";
import { Inbox, AlertCircle } from "lucide-react";

/**
 * Base Shimmer Box for low-CPU, GPU-accelerated skeleton rendering.
 */
export function SkeletonBox({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={`skeleton-shimmer-wrapper rounded-lg ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

/**
 * Enhanced Table Skeleton with realistic header bar and staggered columns.
 */
export function TableSkeleton({
  rows = 6,
  cols = 5,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden shadow-xs">
      {/* Table Header Bar */}
      <div className="px-5 py-3.5 border-b border-border-subtle bg-bg-muted/30 flex items-center gap-4">
        {Array.from({ length: cols }).map((_, c) => (
          <div
            key={c}
            className={`skeleton-shimmer-wrapper h-3.5 rounded ${
              c === 0 ? "w-28" : c === cols - 1 ? "w-16 ml-auto" : "w-20"
            }`}
          />
        ))}
      </div>

      {/* Table Body Rows */}
      <div className="divide-y divide-border-subtle/60 p-2 sm:p-3">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="px-3 py-3.5 flex items-center gap-4">
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className={`skeleton-shimmer-wrapper h-4 rounded ${
                  c === 0
                    ? "w-36 font-mono"
                    : c === 1
                    ? "w-48"
                    : c === cols - 1
                    ? "w-24 ml-auto"
                    : "flex-1 max-w-[120px]"
                }`}
                style={{ opacity: 1 - r * 0.08 }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Single Metric / KPI Card Skeleton
 */
export function CardSkeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-bg-surface rounded-2xl border border-border-subtle p-4 space-y-3 ${className}`}
      aria-hidden="true"
    >
      <div className="flex items-center justify-between">
        <SkeletonBox className="h-3 w-20" />
        <SkeletonBox className="h-8 w-8 rounded-xl" />
      </div>
      <SkeletonBox className="h-7 w-28" />
      <SkeletonBox className="h-2.5 w-16 opacity-70" />
    </div>
  );
}

/**
 * Grid of 6 KPI Cards for Dashboard or Analytics KPI strips
 */
export function KPIGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
}

/**
 * Transaction / Recent Activity List Skeleton
 */
export function TransactionListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3.5 p-1" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center justify-between gap-3">
          <div className="space-y-1.5 flex-1 min-w-0">
            <SkeletonBox className="h-4 w-44" />
            <SkeletonBox className="h-2.5 w-24 opacity-60" />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <SkeletonBox className="h-5 w-14 rounded-full" />
            <SkeletonBox className="h-4 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Interactive AI Chat / Assistant Stream Skeleton
 */
export function InteractiveChatSkeleton() {
  return (
    <div className="space-y-4 p-4 rounded-2xl border border-ai-100 bg-ai-50/20" aria-hidden="true">
      <div className="flex items-center gap-2">
        <SkeletonBox className="w-5 h-5 rounded-full bg-ai-200" />
        <SkeletonBox className="h-3.5 w-32 bg-ai-200" />
      </div>
      <div className="space-y-2 pl-7">
        <SkeletonBox className="h-4 w-full" />
        <SkeletonBox className="h-4 w-5/6" />
        <SkeletonBox className="h-4 w-2/3" />
      </div>
    </div>
  );
}

/**
 * Full Page Route Skeleton used by Next.js streaming (loading.tsx)
 */
export function PageSkeleton() {
  return (
    <div className="space-y-6" aria-label="Loading page content...">
      {/* Header bar skeleton */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-2">
          <SkeletonBox className="h-7 w-48 rounded-xl" />
          <SkeletonBox className="h-3.5 w-72 rounded-lg opacity-70" />
        </div>
        <div className="flex items-center gap-2">
          <SkeletonBox className="h-9 w-24 rounded-xl" />
          <SkeletonBox className="h-9 w-32 rounded-xl" />
        </div>
      </div>

      {/* KPI strip skeleton */}
      <KPIGridSkeleton count={6} />

      {/* Table skeleton */}
      <TableSkeleton rows={7} cols={6} />
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle p-12 flex flex-col items-center text-center">
      <div className="w-12 h-12 rounded-2xl bg-bg-muted flex items-center justify-center mb-3">
        <Inbox className="w-5 h-5 text-text-muted" />
      </div>
      <p className="text-sm font-medium text-text-primary">{title}</p>
      {hint && <p className="text-xs text-text-secondary mt-1 max-w-sm">{hint}</p>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-error-200 p-8 flex flex-col items-center text-center">
      <div className="w-12 h-12 rounded-2xl bg-error-50 flex items-center justify-center mb-3">
        <AlertCircle className="w-5 h-5 text-error-600" />
      </div>
      <p className="text-sm font-medium text-text-primary">Something went wrong</p>
      <p className="text-xs text-error-600 mt-1 max-w-md break-words">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 px-3.5 py-1.5 rounded-xl bg-bg-muted border border-border-subtle text-xs font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
        >
          Try again
        </button>
      )}
    </div>
  );
}
