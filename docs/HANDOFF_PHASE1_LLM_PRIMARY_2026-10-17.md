# HANDOFF — LLM-primary Phase 1 (portable context for a fresh session)
_Dated 2026-10-17. Read this file + `docs/PHASE1_GO_NO_GO_REVIEW_2026-10-16.md`
+ `docs/LLM_PRIMARY_IMPLEMENTATION_PLAN.md` and you have full context._

## 1. Mission and FINAL REQUIRED OUTCOME
Make the ERP's live transaction pipeline LLM-primary at semantic decision
points (two-call split: bounded understanding + hoisted accounting
decision), then run ONE controlled experiment (`LLM_CLASSIFICATION_ENABLED=1`)
under **pre-registered** thresholds and deliver a **go/no-go recommendation
for production activation** — backed by evidence, or a rollback.  The final
deliverable is that decision report.  Success criteria (frozen, unchanged):

1. fallback rate ≤ 15% over ≥ 50 decision-eligible turns (population
   definition NOT yet pinned — see §5 open item);
2. classification-stage p95 ≤ 6 s (frozen contract: stage = CLASSIFICATION
   step elapsed − last PLANNING step elapsed STRICTLY BEFORE it; steps are
   authoritative — the results `timings` mirror gets overwritten);
   separate guard: end-to-end turn p95 ≤ +20% vs baseline 64.0 s (n=14);
3. ZERO new LLM_DECISION sessions FAILED or unverified-attributable
   (baseline contains exactly 1 pre-existing failed LLM_DECISION session);
4. `classifier_gate` §10b repeat-park loops stay 0 (baseline = 0 all owners).
Plus: manual accounting review of ≥ 10 LLM_DECISION sessions.

## 2. Current state (all verified, nothing aspirational)
- **Branch** `llm-primary-baseline` @ `a610b5b` PUSHED; **`origin/main`
  deliberately untouched @ `e9ae94c` (production)**.  Local `main` = same
  commits, never pushed.
- **Tests**: 1167 passed — `python -m pytest app/tests -q
  --ignore=app/tests/test_provider_rate_limit_fallback.py` (that ignore is
  a documented pre-existing google.genai import error).
- **Code shipped on the branch** (vs production e9ae94c): two-call hoist
  (`e383e82`), baseline/record commits, `/api/health` five-flag echo,
  clarification.v1 telemetry stamps, **`account_source` telemetry contract**
  (`e8790cb` — the CLASSIFICATION step now says `account_source:
  LLM_DECISION` when the model's validated account pick was USED; `source`
  keeps the nature's honest provenance and can NEVER show LLM_DECISION on
  explicit-nature turns — criterion 1/§11 read COALESCE(account_source,
  source)).
- **Preview environment (the ONLY authorized experiment env)**:
  `LLM_CLASSIFICATION_ENABLED=1` (preview-scoped) + 14 preview-scoped
  provider vars (TH_API_KEY/TH_BASE_URL/TH_TEXT_MODEL/… and QWEN_*,
  mirrored from local .env — without them decide() dies silently; local
  diag proved LLM_DECISION works via tokenharbor.ai deepseek-v4.1-flash:free).
  Health check: GET /api/health?x-vercel-protection-bypass=<secret>&…
  → flags JSON.  Latest flag-on deployment `dpl_ML6VDxne…` (sha e8790cb).
- **Probe infra (committed)**: `scripts/phase1_probe_setup.py` (idempotent
  probe identity: real Supabase auth user `phase1-probe@erptest.local` id
  `0401e512-5dbb-44fd-bd54-11fcfe18fec3`, ACTIVE OWNER in sandbox org);
  `scripts/phase1_probe_runner.py` (field-routed questionnaire answers,
  numeric defaults amount/salvage/useful_life/date, auto token refresh on
  401, `--only pN-…`, SSE-protection 307 cookie handling).
- **Sandbox org**: `test-traders` = `00000000-0000-4000-8000-000000000010`
  (PKR, ~95 accounts, 146 journals incl. probe writes).  ALL probe traffic
  must stay here — the 17 real companies share this Supabase.
- **Batch 1 (recorded UNSCORED in the go/no-go doc)**: 20 classify turns;
  stage 0.9–5.7 s (20/20 < 6 s, n < 50); account_source=LLM_DECISION 14/20;
  raw fallbacks 6/20 (2 = payment intents the code never consults);
  4 scenarios all COMPLETED end-to-end (van & credit-laptop VERIFIED);
  0 FAILED.  Cold-start stage observations 7.4–12.0 s kept in separate bucket.
- **Docs**: plan (protocol/thresholds/baselines/dry-run 3 rows ✅),
  go/no-go review (measurement contract pinned, batch-1 record),
  BASELINE_SNAPSHOT, LATENCY_QUERIES (§10/10b/10c/11; §11 uses COALESCE).
  Rollback dry-run DONE both paths (env remove + redeploy restores
  all-false; prior deployment isolated throughout).

## 3. Secrets / infra locations (NEVER print values, all gitignored)
- `.env` — SUPABASE_URL/SERVICE_ROLE/ANON, JWT_SECRET, QWEN_*, TH_*,
  ALLOW_LEGACY_JWT_SECRET_AUTH (local only).
- `Supabase.txt` — sbp_ PAT (Management API).
- `.pytest_cache/VERCEL.txt` — Vercel token (last line) + GitHub PAT.
  Team `team_TzcJN36hVtqeUHu2LJ8ZN6hk`, project `prj_uSSvsYLcuKnIRvrlaC6wX6uVgJWk`,
  repo id 1360514032.
- `.pytest_cache/automation.txt` — `x-vercel-protection-bypass` secret.
- `.pytest_cache/probe_login.json` — probe email/password (runner re-logins).
- SQL harness: `python scripts/supabase_sql.py <file>` (Management API,
  single statement, rows returned top-level).

## 4. Operational gotchas (learned the hard way — save an hour)
- **30s command cap** on run_commands: run long work via
  `Start-Process -FilePath python -ArgumentList ... -RedirectStandardOutput
  log -NoNewWindow -PassThru` then poll; python stdout block-buffers to the
  redirect file (flushes at exit) — poll the DB or process state instead.
- PowerShell: `cd` does NOT affect `[IO.File]::*` relative paths → use
  absolute paths; JSON bodies for curl via `[IO.File]::WriteAllText` +
  `--data-binary @file` (PS eats inner quotes); `git push` writes progress
  to stderr (PS reports exit 1) but SUCCEEDS — verify with
  `git fetch origin; git rev-parse origin/llm-primary-baseline`.
- Vercel create-deployment: `POST /v13/deployments` body
  `{"name":"ai-accountant-erp","gitSource":{"type":"github","repoId":"1360514032"
  (STRING),"ref":"llm-primary-baseline"}}` — legacy `git` object silently
  ignored; omit `target` for branch previews.  Env: `POST/DELETE
  /v9/projects/{pid}/env` target `["preview"]`.
- Preview POSTs: query-param bypass is NOT enough — first POST → 307 +
  `_vercel_jwt` Set-Cookie → resend to the BARE path with `Cookie:` header
  (runner `call()` handles it).
- classify decide-layer is gated on `resolve_account_hints=True` (all 3
  `_llm_decision` sites); `_PAYMENT_INTENTS` never consult it; decide
  returns None SILENTLY when provider config missing or reply rejected
  (`llm_classification.reject` appears in stdout logs only).
- Supabase Management API: one statement per query; `journal_lines` FK
  column is NOT `journal_entry_id`.
- Never `Stop-Process python` broadly while background runs are live.

## 5. OPEN ITEMS (exact next steps, in order)
1. **Pin criterion-1 population with GPT** (go/no-go doc §Batch 1):
   proposal = eligible ⇔ intent ∉ `_PAYMENT_INTENTS` AND
   `hints_resolved=true`; requires adding `intent` to the CLASSIFICATION
   step payload (additive stamp, same pattern as account_source) — NOT
   implemented pending approval.
2. If approved: implement intent stamp + tests, commit, redeploy preview
   (gitSource), re-verify health flags.
3. Collect batches toward **≥50 eligible turns** (mix scenarios: ordinary
   expense, fixed-asset, credit, vague, payment — runner supports
   `--batch N --max-probes/--only`); run the §Appendix scoring query per
   batch; cold vs warm recorded separately (never silently drop cold).
4. **Manual accounting review ≥10 LLM_DECISION sessions** (posted account
   vs substance; p2-van and p4-laptop verified sessions are candidates).
5. Score everything vs the frozen thresholds (NO threshold may move to
   fit results); write the final go/no-go recommendation for production
   activation.  If a rollback trigger fires: preview durable path =
   delete `LLM_CLASSIFICATION_ENABLED` env + gitSource redeploy (proven);
   production path never needed unless activation authorized.
6. Boundary until then: flag stays preview-only; Production, `origin/main`
   and the other four AI-stage flags untouched.  Activation = separate
   explicit authorization (would require merging the branch to main).

## 6. Working style expectations (this project's loop)
Evidence-driven: validate every assumption against code/git/DB before
acting; never score an experiment before its operands are pinned; record
findings in the go/no-go doc as they land; commit+push docs/record work to
`llm-primary-baseline` (origin/main stays frozen); secrets never printed;
ask the user (or GPT loop) before threshold/authorization changes.

## Appendix — batch scoring SQL (frozen contract v2)
```sql
with probe as (
  select s.id as sid, s.started_at from ai.execution_sessions s
  where s.organization_id = '00000000-0000-4000-8000-000000000010'
    and s.started_at > timestamptz 'YYYY-MM-DD HH:MM:SS+00'  -- batch start
), stp as (
  select st.execution_session_id as sid, st.description,
         (st.input_summary::jsonb->>'elapsed_ms')::int as elapsed_ms,
         st.input_summary::jsonb as payload
  from ai.execution_steps st join probe p on p.sid = st.execution_session_id
), cls as (
  select sid, payload, elapsed_ms as cls_ms from stp where description='CLASSIFICATION'
), pln as (
  select sid, elapsed_ms as plan_ms from stp where description='PLANNING'
), entry as (
  select c.sid, max(p.plan_ms) as plan_ms
  from cls c join pln p on p.sid = c.sid and p.plan_ms < c.cls_ms group by c.sid
), term as (
  select sid, description as outcome, payload->>'verified' as verified,
         elapsed_ms as turn_ms from stp where description in ('COMPLETED','FAILED')
)
select left(c.sid::text,8) as sid, to_char(pr.started_at,'HH24:MI:SS') as started,
       c.payload->>'source' as source, c.payload->>'account_source' as account_source,
       c.payload->>'transaction_nature' as nature, c.payload->>'account_hint' as hint,
       case when e.plan_ms is not null then c.cls_ms - e.plan_ms end as stage_ms,
       coalesce(term.outcome,'IN_PROGRESS') as outcome, term.verified, term.turn_ms
from cls c join probe pr on pr.sid = c.sid
left join entry e on e.sid = c.sid left join term on term.sid = c.sid
order by pr.started_at;
```

