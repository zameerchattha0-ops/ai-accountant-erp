"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Printer } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { ErrorState, TableSkeleton } from "@/components/shared/States";
import DocTemplate from "./DocTemplate";
import type { PrintDoc } from "./types";

/**
 * DocShell — shared printable-document page frame.
 * Loads the module record via the supplied callback, strips the app
 * chrome on paper (`@media print`), and renders the premium template
 * with a Back link + "Print / PDF" toolbar on screen only.
 */
export default function DocShell({
  backHref,
  backLabel,
  load,
}: {
  backHref: string;
  backLabel: string;
  load: (supabase: ReturnType<typeof createClient>) => Promise<PrintDoc | null>;
}) {
  const [doc, setDoc] = useState<PrintDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    try {
      const d = await load(createClient());
      if (!d) setError("Document not found");
      else setDoc(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load document");
    }
  }, [load]);

  useEffect(() => { run(); }, [run]);

  if (error) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <Link href={backHref} className="text-sm text-ai-600 hover:text-ai-700 inline-flex items-center gap-1.5">
          <ArrowLeft className="w-4 h-4" /> {backLabel}
        </Link>
        <ErrorState message={error} />
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <TableSkeleton rows={8} cols={4} />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5 print:space-y-0">
      {/* Toolbar — screen only */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 print:hidden">
        <Link href={backHref} className="text-sm text-ai-600 hover:text-ai-700 flex items-center gap-1.5">
          <ArrowLeft className="w-4 h-4" /> {backLabel}
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-text-muted">
            {doc.title} · {doc.docNumber}
          </span>
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-bg-surface border border-border-subtle text-sm font-medium text-text-secondary hover:text-text-primary hover:border-ai-200 transition-colors"
          >
            <Printer className="w-4 h-4" /> Print / PDF
          </button>
        </div>
      </div>

      <DocTemplate doc={doc} />
    </div>
  );
}