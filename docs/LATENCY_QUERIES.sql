-- P2-⑪ — FORENSIC LATENCY AUDIT → SQL SCORING QUERIES
-- =====================================================
-- Run read-only against the ERP Supabase project. Sources:
--   ai_execution_steps.description    = step marker (RECEIVED, INTERPRETING,
--                                       ACCOUNTING_REASONING, CLIENT_TTFB, …)
--   ai_execution_steps.step_type      = phase (REASON/RETRIEVE/VALIDATE/
--                                       CONFIRM/EXECUTE/VERIFY/RESPOND)
--   ai_execution_steps.input_summary  = JSON payload; EVERY row now also
--                                       carries elapsed_ms (ms since
--                                       session start, P2-⑪)
--   ai_execution_results.result_payload->'timings'
--                                     = per-request mirror of _phase_elapsed
--                                       (marker -> {elapsed_ms, …}, P2-⑪)
--   ai_execution_sessions.started_at  = server-side start; cold start BEFORE
--                                       this is visible only via CLIENT_TTFB
-- NOTE: legacy ACCOUNTING_REASONING rows written before P1-⑤ may hold
-- JSON sheared by the old 2000-char cap — guarded below with an
-- end-of-string brace check before any ::jsonb cast.

-- 1) CLIENT_TTFB percentiles (cold start + first byte; transport sse|inline)
select
  count(*) as samples,
  percentile_cont(0.5) within group (order by ttfb) as p50_ms,
  percentile_cont(0.95) within group (order by ttfb) as p95_ms
from (
  select (input_summary::jsonb->>'ttfb_ms')::numeric as ttfb
  from ai_execution_steps
  where description = 'CLIENT_TTFB'
    and input_summary is not null
) t;

-- 2) Stage latency p50/p95: started_at -> key durable markers
with marks as (
  select s.id, s.started_at, st.description, st.created_at
  from ai_execution_sessions s
  join ai_execution_steps st on st.execution_session_id = s.id
  where st.description in (
    'INTERPRETING', 'PLANNING', 'CONTEXT_LOADING', 'CLASSIFICATION',
    'ACCOUNTING_REASONING', 'AWAITING_CLARIFICATION',
    'AWAITING_CONFIRMATION', 'EXECUTING', 'COMPLETED', 'FAILED'
  )
)
select
  description,
  count(*) as n,
  percentile_cont(0.5) within group (
    order by extract(epoch from (created_at - started_at)) * 1000) as p50_ms,
  percentile_cont(0.95) within group (
    order by extract(epoch from (created_at - started_at)) * 1000) as p95_ms
from marks
where created_at >= started_at
group by description
order by p50_ms desc nulls last;

-- 3) Reasoning rounds histogram (P0-② effect: rejections/rounds fall)
select
  coalesce((input_summary::jsonb->>'rounds')::int, 0) as rounds,
  count(*) as accounting_reasoning_rows
from ai_execution_steps
where description = 'ACCOUNTING_REASONING'
  and input_summary is not null
  and right(input_summary, 1) in ('}', ']')   -- legacy-shear guard
group by 1
order by 1;

-- 4) DECISION_REJECTED rate per 100 sessions (first-pass-success metric)
select
  count(*) filter (where description = 'DECISION_REJECTED') as rejections,
  count(distinct execution_session_id) as sessions,
  round(
    100.0 * count(*) filter (where description = 'DECISION_REJECTED')
    / nullif(count(distinct execution_session_id), 0), 2
  ) as rejections_per_100_sessions
from ai_execution_steps;

-- 5) Evidence observability: requested vs seeded (P1-⑤) vs prefetched (P1-⑩)
select
  count(*) filter (where description = 'EVIDENCE_REQUESTED')  as requested_events,
  count(*) filter (where description = 'EVIDENCE_SEEDED')     as seeded_events,
  count(*) filter (where description = 'EVIDENCE_PREFETCH')   as prefetch_events,
  count(*) filter (where description = 'EVIDENCE_RETURNED')   as returned_events,
  count(distinct execution_session_id) as sessions_with_evidence
from ai_execution_steps;

-- 6) p50/p95 straight from the per-request phase mirror (preferred:
--    sub-second precision, includes post-reasoning trims)
select
  t.marker,
  count(*) as n,
  percentile_cont(0.5) within group (
    order by (t.value->>'elapsed_ms')::numeric) as p50_ms,
  percentile_cont(0.95) within group (
    order by (t.value->>'elapsed_ms')::numeric) as p95_ms
from ai_execution_results r,
     lateral jsonb_each(r.result_payload::jsonb->'timings') as t(marker, value)
where r.result_payload is not null
  and r.result_payload::jsonb ? 'timings'
group by t.marker
order by p50_ms desc nulls last;

-- 7) Flat per-session timeline from the mirror (debugging one bad run)
select
  r.execution_session_id,
  t.marker,
  (t.value->>'elapsed_ms')::numeric as elapsed_ms,
  t.value as extra
from ai_execution_results r,
     lateral jsonb_each(r.result_payload::jsonb->'timings') as t(marker, value)
where r.result_payload is not null
  and r.result_payload::jsonb ? 'timings'
order by r.execution_session_id, elapsed_ms;

-- 8) LLM-call counts (planning calls vs reasoning runs)
select
  count(*) filter (
    where description = 'INTERPRETING'
      and input_summary is not null
      and right(input_summary, 1) in ('}', ']')
      and (input_summary::jsonb->>'source') = 'llm_planning'
  ) as planning_llm_calls,
  count(*) filter (where description = 'ACCOUNTING_REASONING') as reasoning_runs
from ai_execution_steps;
