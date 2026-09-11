"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import StatusBadge from "./StatusBadge";
import { cn } from "@/lib/utils/cn";

/**
 * StatusMenu — click-to-change voucher status, inline on any list.
 *
 * Wraps the StatusBadge in a small dropdown offering ONLY the
 * business-valid transitions for the row's current status (never free
 * choice — financial statuses like PAID/OVERDUE stay system-driven from
 * payments/aging). The update PATCHes the row (RLS-scoped) and reports
 * back via onUpdated/onError so lists reload without a page refresh.
 */
export default function StatusMenu({
  table,
  documentId,
  status,
  transitions,
  onUpdated,
  onError,
}: {
  table: string;
  documentId: string;
  status: string;
  /** status → allowed next statuses. Empty/absent = badge only. */
  transitions: Record<string, string[]>;
  onUpdated: () => void;
  onError?: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const nexts = transitions[status] ?? [];

  /* Outside click / Escape closes the menu */
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const apply = async (next: string) => {
    setBusy(true);
    const supabase = createClient();
    const { error: updError } = await supabase
      .from(table)
      .update({ status: next })
      .eq("id", documentId);
    setBusy(false);
    setOpen(false);
    if (updError) {
      onError?.(updError.message);
      return;
    }
    onUpdated();
  };

  /* No valid transition → plain badge (system-driven statuses) */
  if (nexts.length === 0) {
    return <StatusBadge status={status} />;
  }

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Change status from ${status}`}
        className="inline-flex items-center gap-1 rounded-full focus:outline-none focus:ring-2 focus:ring-ai-200 transition-transform hover:scale-[1.04] active:scale-95"
      >
        <StatusBadge status={status} />
        {busy ? (
          <Loader2 className="w-3 h-3 animate-spin text-text-muted" />
        ) : (
          <ChevronDown
            className={cn("w-3 h-3 text-text-muted transition-transform", open && "rotate-180")}
          />
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full mt-1.5 w-44 bg-bg-surface rounded-xl shadow-lg border border-border-subtle py-1 z-30"
          style={{ animation: "statusMenuIn 0.22s cubic-bezier(0.19,1,0.22,1) both" }}
        >
          <p className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-widest text-text-muted">
            Change status
          </p>
          {nexts.map((s) => (
            <button
              key={s}
              type="button"
              role="menuitem"
              onClick={() => apply(s)}
              disabled={busy}
              className="w-full flex items-center px-3 py-2 text-left hover:bg-bg-muted transition-colors disabled:opacity-50"
            >
              <StatusBadge status={s} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}