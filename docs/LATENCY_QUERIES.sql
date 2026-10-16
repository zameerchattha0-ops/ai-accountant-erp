-- P2-⑪ — FORENSIC LATENCY AUDIT → SQL SCORING QUERIES
-- =====================================================
-- SCHEMA NOTE (2026-10-16): every table reference is schema-qualified
-- (ai.execution_steps / ai.execution_sessions / ai.execution_results).
-- There are NO public.ai_% compatibility views — bare names fail at run
-- time.  Verified against information_schema via Management API.
-- Run read-only against the ERP Supabase project. Sources:
--   ai.execution_steps.description    = step marker (RECEIVED, INTERPRETING,
--                                       ACCOUNTING_REASONING, CLIENT_TTFB, …)
--   ai.execution_steps.step_type      = phase (REASON/RETRIEVE/VALIDATE/
--                                       CONFIRM/EXECUTE/VERIFY/RESPOND)
--   ai.execution_steps.input_summary  = JSON payload; EVERY row now also
--                                       carries elapsed_ms (ms since
--                                       session start, P2-⑪)
--   ai.execution_results.result_payload->'timings'
--                                     = per-request mirror of _phase_elapsed
--                                       (marker -> {elapsed_ms, …}, P2-⑪)
--   ai.execution_sessions.started_at  = server-side start; cold start BEFORE
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
  from ai.execution_steps
  where description = 'CLIENT_TTFB'
    and input_summary is not null
) t;

-- 2) Stage latency p50/p95: started_at -> key durable markers
with marks as (
  select s.id, s.started_at, st.description, st.created_at
  from ai.execution_sessions s
  join ai.execution_steps st on st.execution_session_id = s.id
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
from ai.execution_steps
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
from ai.execution_steps;

-- 5) Evidence observability: requested vs seeded (P1-⑤) vs prefetched (P1-⑩)
select
  count(*) filter (where description = 'EVIDENCE_REQUESTED')  as requested_events,
  count(*) filter (where description = 'EVIDENCE_SEEDED')     as seeded_events,
  count(*) filter (where description = 'EVIDENCE_PREFETCH')   as prefetch_events,
  count(*) filter (where description = 'EVIDENCE_RETURNED')   as returned_events,
  count(distinct execution_session_id) as sessions_with_evidence
from ai.execution_steps;

-- 6) p50/p95 straight from the per-request phase mirror (preferred:
--    sub-second precision, includes post-reasoning trims)
select
  t.marker,
  count(*) as n,
  percentile_cont(0.5) within group (
    order by (t.value->>'elapsed_ms')::numeric) as p50_ms,
  percentile_cont(0.95) within group (
    order by (t.value->>'elapsed_ms')::numeric) as p95_ms
from ai.execution_results r,
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
from ai.execution_results r,
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
from ai.execution_steps;

-- 9) WAVE A — SINGLE-OWNER DIVERGENCE METRIC  (E:\Qoder\AUDIT_REPORT.md §8)
-- -----------------------------------------------------------------------
-- Step marker INTENT_COMPARISON records MODEL_INTENT vs LEGACY_INTENT for
-- every turn that reached the planner.  Wave B (model becomes authoritative)
-- may NOT begin until >= 200 comparable turns are collected AND every
-- divergence below is classified (which side was wrong, and why).

-- 9a) result distribution
select
  input_summary::jsonb->>'result' as result,
  count(*)                        as turns,
  count(distinct execution_session_id) as sessions
from ai.execution_steps
where description = 'INTENT_COMPARISON'
  and input_summary is not null
  and right(input_summary, 1) in ('}', ']')   -- legacy-shear guard
group by 1
order by turns desc;

-- 9b) divergence rate over COMPARABLE turns (both intents canonical)
with comp as (
  select
    input_summary::jsonb->>'model_intent' as model_intent,
    input_summary::jsonb->>'legacy_intent' as legacy_intent,
    input_summary::jsonb->>'result'        as result
  from ai.execution_steps
  where description = 'INTENT_COMPARISON'
    and input_summary is not null
    and right(input_summary, 1) in ('}', ']')
)
select
  count(*) filter (where result = 'AGREEMENT')         as agreement,
  count(*) filter (where result = 'DIVERGENT_INTENT')  as divergent,
  count(*) filter (where result = 'MODEL_ABSENT')      as model_absent,
  count(*) filter (where result = 'MODEL_NONCANONICAL') as model_noncanonical,
  count(*) filter (where result = 'LEGACY_ABSENT')     as legacy_absent,
  round(
    100.0 * count(*) filter (where result = 'DIVERGENT_INTENT')
    / nullif(count(*) filter (where result in ('AGREEMENT', 'DIVERGENT_INTENT')), 0),
    2
  ) as divergence_pct_of_comparable_turns
from comp;

-- 9c) WHICH intents disagree — classify every row before Wave B (§8 gate)
with comp as (
  select
    input_summary::jsonb->>'model_intent'  as model_intent,
    input_summary::jsonb->>'legacy_intent'  as legacy_intent,
    input_summary::jsonb->>'result'         as result
  from ai.execution_steps
  where description = 'INTENT_COMPARISON'
    and input_summary is not null
    and right(input_summary, 1) in ('}', ']')
)
select model_intent, legacy_intent, count(*) as turns
from comp
where result = 'DIVERGENT_INTENT'
group by 1, 2
order by turns desc
limit 25;

-- 10) CLARIFICATION TELEMETRY (clarification.v1) — per-owner park rate,
--     branch mix and latency, with REAL denominators.  coalesce(branch,
--     source) yields every instrumentation label: planner_questionnaire,
--     classifier_nature_4way, classifier_config_gap, classifier_treatment,
--     account_creation_gap (plus every pre-existing owner — their source
--     values are a stability contract and never renamed).  The classifier
--     GATE is distinguishable from execution PREFLIGHT by source alone.
--     Rate denominator: RECEIVED = turns.
with clar as (
  select
    st.execution_session_id,
    (st.input_summary::jsonb->>'source')        as source,
    (st.input_summary::jsonb->>'branch')        as branch,
    (st.input_summary::jsonb->>'telemetry')     as telemetry,
    (st.input_summary::jsonb->>'elapsed_ms')::numeric as parked_ms
  from ai.execution_steps st
  where st.description = 'AWAITING_CLARIFICATION'
    and st.input_summary is not null
    and right(st.input_summary, 1) = '}'      -- legacy sheared rows guard
)
select
  coalesce(nullif(clar.branch, ''), clar.source) as clarification_owner,
  count(*)                                        as parked_turns,
  count(distinct clar.execution_session_id)       as sessions,
  round(
    count(*)::numeric
    / nullif((select count(*) from ai.execution_steps
              where description = 'RECEIVED'), 0),
    4
  )                                               as park_rate_per_turn,
  percentile_cont(0.5) within group (order by clar.parked_ms) as p50_parked_ms,
  percentile_cont(0.95) within group (order by clar.parked_ms) as p95_parked_ms
from clar
group by 1
order by parked_turns desc;

-- 10b) REPEAT-PARK profile — GPT review point: distinct sessions alone do
--      NOT measure repeated rounds.  A source with 3 parked turns across
--      1 session is a LOOP; the same 3 turns across 3 sessions is breadth.
--      Per owner: affected sessions, how many parked >= 2 times, the worst
--      single-session loop, and average parks per affected session.  A low
--      park rate with high repeat counts still deserves consolidation —
--      frequency alone must not gate the decision.
with clar as (
  select
    st.execution_session_id as sid,
    coalesce(nullif(st.input_summary::jsonb->>'branch', ''),
             st.input_summary::jsonb->>'source') as owner
  from ai.execution_steps st
  where st.description = 'AWAITING_CLARIFICATION'
    and st.input_summary is not null
    and right(st.input_summary, 1) = '}'
),
per_session as (
  select owner, sid, count(*) as parks
  from clar
  group by 1, 2
)
select
  owner,
  sum(parks)                                        as parked_turns,
  count(*)                                          as affected_sessions,
  count(*) filter (where parks >= 2)                as sessions_with_repeat_parks,
  max(parks)                                        as worst_session_parks,
  round(avg(parks), 2)                              as avg_parks_per_session
from per_session
group by owner
order by parked_turns desc;

-- 10c) SAME-ISSUE loops — the loops consolidation would actually break:
--      sessions that parked >= 2 times under the same owner with the SAME
--      required_fields (e.g. account_configuration asked round after
--      round).  Field-set granularity is deliberate; the per-event `gap`
--      and `question` payloads name the specific ledger for drill-down.
--      required_fields is compared as its JSON text form, which groups
--      identically for identical field sets.
with clar as (
  select
    st.execution_session_id as sid,
    coalesce(nullif(st.input_summary::jsonb->>'branch', ''),
             st.input_summary::jsonb->>'source') as owner,
    st.input_summary::jsonb->>'required_fields' as required_fields
  from ai.execution_steps st
  where st.description = 'AWAITING_CLARIFICATION'
    and st.input_summary is not null
    and right(st.input_summary, 1) = '}'
),
per_issue as (
  select owner, required_fields, sid, count(*) as parks
  from clar
  group by 1, 2, 3
)
select
  owner,
  required_fields,
  count(*)         as sessions_looped,
  sum(parks)       as total_parks,
  max(parks)       as worst_session_parks
from per_issue
where parks >= 2
group by 1, 2
order by sessions_looped desc, total_parks desc;

-- 11) PHASE 1 JOURNAL-OUTCOME VERIFICATION — decision source vs what the
--     books ACTUALLY got.  A source label proves what the model decided;
--     this proves the session completed, verified, and did not fail.
--     Per decision source (LLM_DECISION vs deterministic chain): sessions,
--     completed, completed-and-verified, failed.  COMPLETED payloads carry
--     `verified` (production trail evidence).  Run segmented by experiment
--     window (sessions.started_at) to compare against the baseline.
with cls as (
  select distinct on (st.execution_session_id)
    st.execution_session_id as sid,
    -- account_source (Phase 1 telemetry contract, 2026-10-16) marks "the
    -- model's validated account decision was USED"; legacy rows predate the
    -- field and fall back to `source`.  `source` alone is insufficient on
    -- explicit-nature turns, where it keeps the nature's honest provenance.
    coalesce(st.input_summary::jsonb->>'account_source',
             st.input_summary::jsonb->>'source') as decision_source
  from ai.execution_steps st
  where st.description = 'CLASSIFICATION'
    and st.input_summary is not null
    and right(st.input_summary, 1) = '}'
  order by st.execution_session_id, st.step_order desc
),
terminal as (
  select
    st.execution_session_id as sid,
    st.description as outcome,
    st.input_summary::jsonb->>'verified' as verified
  from ai.execution_steps st
  where st.description in ('COMPLETED', 'FAILED', 'REJECTED')
    and st.input_summary is not null
    and right(st.input_summary, 1) = '}'
)
select
  coalesce(cls.decision_source, '(none)') as decision_source,
  count(distinct terminal.sid)                                     as sessions,
  count(distinct terminal.sid) filter (where outcome = 'COMPLETED') as completed,
  count(distinct terminal.sid) filter (
    where outcome = 'COMPLETED' and verified = 'true'
  )                                                                as completed_verified,
  count(distinct terminal.sid) filter (where outcome = 'FAILED')   as failed
from terminal
join cls on cls.sid = terminal.sid
group by 1
order by sessions desc;

