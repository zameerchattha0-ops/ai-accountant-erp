"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useOrgRole } from "@/lib/hooks/useOrgRole";
import { cn } from "@/lib/utils/cn";

/**
 * Work Stream F: role-gated DRAFT delete for document modules.
 *
 * The database is the enforcement layer (RLS delete = Owner/Admin only,
 * status-guard trigger = DRAFT-only + linked-journal refusal). This button
 * simply mirrors that policy in the UI: it renders ONLY for Owner/Admin,
 * so a user never discovers permissions through an error message.
 */
export default function DraftDeleteButton({
  table,
  documentId,
  label = "draft document",
  onDeleted,
  onError,
}: {
  table: string;
  documentId: string;
  label?: string;
  onDeleted?: () => void;
  onError?: (message: string) => void;
}) {
  const { isAdmin, loading } = useOrgRole();
  const [busy, setBusy] = useState(false);

  if (loading || !isAdmin) return null;

  const handle = async (ev: React.MouseEvent) => {
    ev.stopPropagation();
    if (!window.confirm(`Delete this ${label}? This cannot be undone.`)) return;
    setBusy(true);
    const supabase = createClient();
    const { error } = await supabase.from(table).delete().eq("id", documentId);
    setBusy(false);
    if (error) {
      // Surface DB refusals honestly (e.g. linked journal exists).
      onError?.(error.message);
    } else {
      onDeleted?.();
    }
  };

  return (
    <button
      onClick={handle}
      disabled={busy}
      title={`Delete ${label} (Owner/Admin only; DRAFT documents without a linked journal)`}
      aria-label={`Delete ${label}`}
      className={cn(
        "p-1 rounded text-text-muted hover:text-error-600 hover:bg-error-50",
        "disabled:opacity-50 transition-colors"
      )}
    >
      <Trash2 className={cn("w-3.5 h-3.5", busy && "animate-pulse")} />
    </button>
  );
}
