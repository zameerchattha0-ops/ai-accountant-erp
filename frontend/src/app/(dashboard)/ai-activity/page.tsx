"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clock,
  HelpCircle,
  ListOrdered,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { aiGetSession, aiGetSessions } from "@/lib/api/client";
import {
  STATUS_FILTERS,
  formatDuration,
  formatWhen,
  humanise,
  isActiveSession,
  isWriteTool,
  messageOf,
  resultState,
  sessionDurationSeconds,
  sessionHeadline,
  toolLabel,
  trailCounts,
  visibleSessions,
} from "@/lib/ai-activity/logic";
import Modal from "@/components/shared/Modal";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/States";
import type {
  ActivityFeed,
  SessionBundle,
  SessionSummary,
} from "@/lib/types/api";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

/** How long to wait after the last keystroke before asking the server. */
const SEARCH_DEBOUNCE_MS = 300;

/** One labelled figure in the KPI strip. */
function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle p-4">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
        {value}
      </p>
    </div>
  );
}

/** A titled block inside the detail sheet — an empty one explains itself. */
function Section({
  icon,
  title,
  empty,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  empty: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-ai-600">{icon}</span>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          {title}
        </h3>
      </div>
      {children ? (
        <div className="space-y-2">{children}</div>
      ) : (
        <p className="text-xs text-text-muted">{empty}</p>
      )}
    </section>
  );
}

export default function AIActivityPage() {
  const [feed, setFeed] = useState<ActivityFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");

  // Server-side search results — used ONLY when the loaded feed is incomplete
  // (see `truncated`); null means "use the loaded feed".
  const [serverItems, setServerItems] = useState<SessionSummary[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [detail, setDetail] = useState<SessionSummary | null>(null);
  const [bundle, setBundle] = useState<SessionBundle | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setFeed(await aiGetSessions());
    } catch (e) {
      setError(messageOf(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadDetail = useCallback(async (sessionId: string) => {
    setBundleError(null);
    try {
      setBundle(await aiGetSession(sessionId));
    } catch (e) {
      setBundleError(messageOf(e));
    }
  }, []);

  const rows = useMemo(() => feed?.items ?? [], [feed]);
  const counts = feed?.counts ?? {};
  const truncated = feed?.truncated ?? false;

  // Server-side search: needed only when the loaded page is INCOMPLETE (the
  // feed exceeded the read ceiling) — then the browser's copy can no longer
  // answer the query.  Debounced, and the previous list stays visible while it
  // runs (no flicker).
  useEffect(() => {
    if (!truncated) {
      setServerItems(null);
      return;
    }
    const handle = setTimeout(async () => {
      setSearching(true);
      try {
        const result = await aiGetSessions(undefined, search, status);
        setServerItems(result.items);
      } catch {
        // Fall back to the loaded feed rather than blanking the list.
        setServerItems(null);
      } finally {
        setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [truncated, feed, search, status]);

  const filtered = useMemo(
    () => visibleSessions(rows, search, status, serverItems, truncated),
    [rows, search, status, serverItems, truncated]
  );

  /** Honest state banners — each names a real limitation instead of hiding it. */
  const notices: string[] = [];
  if (truncated && feed) {
    notices.push(
      `Only the first ${feed.total} runs are shown — this feed is larger, and ` +
        "the totals describe these runs only."
    );
  }

  const openDetail = (row: SessionSummary) => {
    setDetail(row);
    setBundle(null);
    setBundleError(null);
    void loadDetail(row.id);
  };

  /**
   * The outcome block — three honest states, because "no result" means three
   * different things: recorded / still running / finished-but-never-recorded.
   */
  const renderOutcome = (b: SessionBundle) => {
    const result = b.results;
    if (result) {
      const entities = Array.isArray(result.affected_entities)
        ? result.affected_entities.length
        : 0;
      return (
        <div className="rounded-xl border border-border-subtle bg-bg-muted px-4 py-3">
          <div className="flex items-center gap-2 flex-wrap">
            <CheckCircle2 className="w-4 h-4 text-success-600" />
            <span className="text-sm font-medium text-text-primary">Outcome</span>
            {result.verification_status && (
              <span className="text-[11px] text-text-muted">
                {humanise(String(result.verification_status))}
              </span>
            )}
          </div>
          {result.summary && (
            <p className="mt-1.5 text-sm text-text-secondary">{result.summary}</p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
            {result.action_type && (
              <span>Action: {humanise(String(result.action_type))}</span>
            )}
            {entities > 0 && (
              <span>
                {entities} affected record{entities === 1 ? "" : "s"}
              </span>
            )}
            {result.completed_at && <span>{formatWhen(result.completed_at)}</span>}
          </div>
        </div>
      );
    }
    const pending = resultState(b.session, null) === "pending";
    return (
      <div className="rounded-xl border border-dashed border-border-default px-4 py-3">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-text-muted" />
          <span className="text-sm font-medium text-text-secondary">
            {pending ? "No outcome yet" : "No outcome recorded"}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-muted">
          {pending
            ? "This run has not finished, so no result has been written down yet."
            : "This run finished but wrote no result row — nothing can be claimed about what it changed."}
        </p>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Activity"
        subtitle="Your agent runs — what you asked, what it planned, what it wrote to your books, and what you approved. Read-only."
        actions={
          <button
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border-default bg-bg-surface px-3.5 py-2 text-sm font-medium text-text-secondary hover:bg-bg-muted transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile label="Runs" value={String(counts.ALL ?? rows.length)} />
        <Tile label="Completed" value={String(counts.COMPLETED ?? 0)} />
        <Tile label="Waiting on you" value={String(counts.WAITING_FOR_USER ?? 0)} />
        <Tile label="Failed" value={String(counts.FAILED ?? 0)} />
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search what you asked..."
            className={`${inputCls} pl-9`}
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={`${inputCls} sm:w-64`}
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option} value={option}>
              {option === "ALL"
                ? `All runs (${counts.ALL ?? rows.length})`
                : `${option === "WAITING_FOR_USER" ? "waiting on you" : humanise(option)} (${counts[option] ?? 0})`}
            </option>
          ))}
        </select>
      </div>

      {searching && (
        <p className="text-xs text-text-muted">Searching the full feed…</p>
      )}

      {notices.length > 0 && (
        <div className="rounded-xl border border-warning-100 bg-warning-50 px-4 py-3 text-sm text-text-primary space-y-1">
          {notices.map((notice) => (
            <p key={notice}>{notice}</p>
          ))}
        </div>
      )}

      {!feed && !error ? (
        <TableSkeleton rows={6} cols={4} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={rows.length ? "No runs match this filter" : "No AI activity yet"}
          hint={
            rows.length
              ? undefined
              : "Ask the agent something from the chat — for example \"Show me this month's expenses\". Every run appears here afterwards."
          }
        />
      ) : (
        <div className="bg-bg-surface rounded-2xl border border-border-subtle divide-y divide-border-subtle overflow-hidden">
          {filtered.map((row) => {
            const duration = sessionDurationSeconds(row);
            const active = isActiveSession(String(row.status));
            const failed = String(row.status) === "FAILED";
            const done = String(row.status) === "COMPLETED";
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => openDetail(row)}
                className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-bg-muted/50 transition-colors"
              >
                <span className="mt-1.5 shrink-0">
                  {active ? (
                    <span className="block h-2 w-2 rounded-full bg-ai-500 animate-pulse" />
                  ) : (
                    <span
                      className={`block h-2 w-2 rounded-full ${
                        failed
                          ? "bg-error-500"
                          : done
                            ? "bg-success-500"
                            : "bg-border-strong"
                      }`}
                    />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 flex-wrap">
                    <StatusBadge status={String(row.status)} />
                    {row.current_phase &&
                      String(row.current_phase) !== String(row.status) && (
                        <span className="text-[11px] text-text-muted">
                          {humanise(String(row.current_phase))}
                        </span>
                      )}
                  </span>
                  <span className="mt-1 block text-sm font-medium text-text-primary truncate">
                    {sessionHeadline(row)}
                  </span>
                  <span className="mt-0.5 block text-xs text-text-muted">
                    {formatWhen(row.created_at)}
                    {duration !== null && ` · took ${formatDuration(duration)}`}
                    {active && " · in progress"}
                  </span>
                </span>
                <span className="self-center shrink-0 text-xs font-medium text-ai-600">
                  Open
                </span>
              </button>
            );
          })}
        </div>
      )}

      <Modal
        open={detail !== null}
        onClose={() => setDetail(null)}
        title="Run details"
        wide
      >
        {bundleError ? (
          <ErrorState
            message={bundleError}
            onRetry={() => detail && void loadDetail(detail.id)}
          />
        ) : !bundle ? (
          <TableSkeleton rows={6} cols={4} />
        ) : (
          <div className="space-y-5">
            <div>
              <div className="flex items-center gap-1.5 text-ai-600">
                <Sparkles className="w-4 h-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">
                  What you asked
                </span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-text-primary">
                {sessionHeadline(bundle.session)}
              </p>
              <div className="mt-2 flex items-center gap-2 flex-wrap">
                <StatusBadge status={String(bundle.session.status)} />
                {bundle.session.current_phase && (
                  <span className="text-xs text-text-muted">
                    {humanise(String(bundle.session.current_phase))}
                  </span>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Tile label="Started" value={formatWhen(bundle.session.started_at)} />
              <Tile
                label="Finished"
                value={formatWhen(bundle.session.completed_at)}
              />
              <Tile
                label="Duration"
                value={formatDuration(sessionDurationSeconds(bundle.session))}
              />
              <Tile
                label="Tools called"
                value={String(trailCounts(bundle).toolCalls)}
              />
            </div>

            {renderOutcome(bundle)}

            <Section
              icon={<ListOrdered className="w-4 h-4" />}
              title="Steps"
              empty="No steps were recorded for this run."
            >
              {bundle.steps.length > 0 &&
                bundle.steps.map((step, index) => (
                  <div
                    key={`${step.step_order}-${index}`}
                    className="rounded-xl border border-border-subtle px-3 py-2"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] tabular-nums text-text-muted">
                        #{step.step_order}
                      </span>
                      <span className="text-xs font-medium text-text-primary">
                        {humanise(step.step_type)}
                      </span>
                      <StatusBadge status={step.status} />
                    </div>
                    {step.description && (
                      <p className="mt-1 text-xs text-text-secondary">
                        {step.description}
                      </p>
                    )}
                    {step.output_summary && (
                      <p className="mt-1 text-xs text-text-muted">
                        {step.output_summary}
                      </p>
                    )}
                    {step.error_details && (
                      <p className="mt-1 text-xs text-error-600">
                        {step.error_details}
                      </p>
                    )}
                  </div>
                ))}
            </Section>

            <Section
              icon={<Wrench className="w-4 h-4" />}
              title="Tools called"
              empty="No tool calls recorded for this run."
            >
              {bundle.tool_calls.length > 0 &&
                bundle.tool_calls.map((call, index) => {
                  const write = isWriteTool(call);
                  const unresolved = call.tool_read_only == null;
                  return (
                    <div
                      key={`${call.call_order}-${index}`}
                      className="rounded-xl border border-border-subtle px-3 py-2"
                    >
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-text-primary">
                          {toolLabel(call)}
                        </span>
                        <span
                          className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                            write
                              ? "bg-warning-50 text-warning-700"
                              : unresolved
                                ? "bg-bg-muted text-text-muted"
                                : "bg-info-50 text-info-700"
                          }`}
                        >
                          {write
                            ? "Changed your books"
                            : unresolved
                              ? "Read/write unknown"
                              : "Read-only"}
                        </span>
                        <StatusBadge status={call.status} />
                      </div>
                      {call.error_details && (
                        <p className="mt-1 text-xs text-error-600">
                          {call.error_details}
                        </p>
                      )}
                    </div>
                  );
                })}
            </Section>
            <Section
              icon={<HelpCircle className="w-4 h-4" />}
              title="Questions it asked"
              empty="It did not need to ask you anything for this run."
            >
              {bundle.clarifications.length > 0 &&
                bundle.clarifications.map((item, index) => (
                  <div
                    key={index}
                    className="rounded-xl border border-border-subtle px-3 py-2"
                  >
                    <p className="text-sm text-text-primary">{item.question}</p>
                    {item.reason && (
                      <p className="mt-0.5 text-xs text-text-muted">
                        Why: {item.reason}
                      </p>
                    )}
                    <p className="mt-1 text-xs">
                      {item.user_response ? (
                        <span className="text-text-secondary">
                          You answered: {item.user_response}
                        </span>
                      ) : (
                        <span className="text-warning-700">
                          Still waiting for your answer
                        </span>
                      )}
                    </p>
                  </div>
                ))}
            </Section>

            <Section
              icon={<ShieldCheck className="w-4 h-4" />}
              title="Approvals"
              empty="Nothing needed your approval for this run."
            >
              {bundle.confirmations.length > 0 &&
                bundle.confirmations.map((item, index) => (
                  <div
                    key={index}
                    className="rounded-xl border border-border-subtle px-3 py-2"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-text-primary">
                        {humanise(item.action_type)}
                      </span>
                      <span className="text-[11px] text-text-muted">
                        {humanise(item.risk_level)} risk
                      </span>
                      <span
                        className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                          item.user_confirmed === true
                            ? "bg-success-50 text-success-700"
                            : item.user_confirmed === false
                              ? "bg-error-50 text-error-700"
                              : "bg-warning-50 text-warning-700"
                        }`}
                      >
                        {item.user_confirmed === true
                          ? "Approved"
                          : item.user_confirmed === false
                            ? "Declined"
                            : "Awaiting your decision"}
                      </span>
                    </div>
                    {item.description && (
                      <p className="mt-1 text-xs text-text-secondary">
                        {item.description}
                      </p>
                    )}
                  </div>
                ))}
            </Section>
          </div>
        )}
      </Modal>

    </div>
  );
}

