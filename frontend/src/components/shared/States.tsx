import { Inbox, AlertCircle } from "lucide-react";

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle overflow-hidden">
      <div className="animate-pulse p-4 space-y-3">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-4">
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className="h-4 bg-bg-muted rounded flex-1"
                style={{ maxWidth: `${100 / cols}%` }}
              />
            ))}
          </div>
        ))}
      </div>
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

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-error-200 p-8 flex flex-col items-center text-center">
      <div className="w-12 h-12 rounded-2xl bg-error-50 flex items-center justify-center mb-3">
        <AlertCircle className="w-5 h-5 text-error-600" />
      </div>
      <p className="text-sm font-medium text-text-primary">Something went wrong</p>
      <p className="text-xs text-error-600 mt-1 max-w-md break-words">{message}</p>
    </div>
  );
}
