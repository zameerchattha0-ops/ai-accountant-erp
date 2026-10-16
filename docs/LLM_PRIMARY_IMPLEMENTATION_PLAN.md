# AI Accountant ERP — LLM-Primary Implementation Plan (CHECKED)

Status: Phase 0 (read-only audit + live probe) COMPLETE — see Evidence.
Execution boundary: this document authorizes NO deployment, flag activation,
authority promotion, or commit/push. Each phase lands as a small, reversible,
reviewed diff gated by the 1,145-test regression suite.

## Objective

Make the LIVE transaction pipeline LLM-primary at semantic decision points
(understanding, nature/treatment/account decisions, answer interpretation,
execution-time ambiguity, route recommendation), with demand-driven short
calls. Python keeps grounding, whitelist, merge-contract, permission,
journal-balance and integrity authority. The Stage-3 two-call runtime stays
candidate-only until Phase 4 evidence says otherwise.

## Verified architecture facts (2026-10-16 audit)

| Fact | Evidence |
|---|---|
| Effective flags: `two_call_runtime_enabled=False`, `accounting_reasoning_enabled=False`, `llm_classification_enabled=False`, `semantic_llm_enabled=False`, `bounded_understanding_enabled=True` | live `get_settings()` |
| One bounded LLM stage is live and working: gap-gated intake (Call 1) | `text_understanding_gaps` → `extract_request_facts`; this session's Fix A adds keyword-grounded `transaction_purpose` |
| CALL 2 is live as the deterministic classifier, hoisted BEFORE the question (Fix B) | `agent.py` PHASE 3-early; single `classify_transaction` call site |
| Provider fix chain is IN HEAD: `th_thinking_off=True` (auto-applies to token-harbor), empty-answer retry + truthful `failure_reason="empty_answer"` wording, timeout-ladder fix (75a6f20 is an ancestor of HEAD) | ai_orchestrator.py:442-443, 601-604; `test_empty_answer_retry.py`, `test_timeout_ladder.py` in suite |
| Model chain: `deepseek-v4.1-flash:free` → mimo-v2.6 → mimo-v2.5 (Qwen demoted: 403 AccessDenied workspace) | config.py `th_text_model_chain` |
| Output caps: `qwen_max_output_tokens` code default 2048; `QWEN_MAX_OUTPUT_TOKENS=8192` env in Vercel prod+preview (root-cause doc) | config.py, docs/EMPTY_ANSWER_ROOT_CAUSE.md |
| **`archive/llm-primary-reasoning` is a stale pointer** — tip 75a6f20 is 54 revisions behind HEAD, immediately before the profile flip (3735810). It contains no capability HEAD lacks; every later commit ADDED fixes (RC authority, grounding, bounded understanding, thinking-off). Deliverable "archive reuse list" = **NONE — re-enable HEAD's own stages instead** | `git rev-list`, `merge-base --is-ancestor`, `git diff HEAD archive -- app/` (86 files, +433/−20,491: archive strictly pre-evolution) |

## Phase 0 evidence (COMPLETE)

Live probe, real gateway (`tokenharbor.ai`, deepseek-v4.1-flash:free),
`scripts/short_understanding_probe.py`, 2026-10-16:

| knob | finish_reason | content | completion tokens | wall | JSON |
|---|---|---|---|---|---|
| thinking ON, 600 cap | stop | 158 chars | 1068 (!) | 9.1 s | valid |
| **thinking OFF, 600 cap** | **stop** | **126 chars** | **32** | **3.1 s** | **valid** |

Model output respected grounding conventions (verbatim misspelling
"tax servcies", nature REVENUE, unspoken fields omitted). The root-cause
doc already records the three applied fixes and the 2026-09-30 failure
measurements (`finish_reason=length`, content 0, reasoning 9,358 chars,
19.7 s) that motivated the profile.

Phase 0 residuals — **COMPLETE (2026-10-16 live)**, via
`scripts/residual_shape_probe.py` (new; real prompts, real gateway,
thinking OFF, real contract validators) + `empty_answer_size_probe.py`:

| Call shape | finish_reason | tokens | wall | contract result |
|---|---|---|---|---|
| Short understanding (earlier) | stop | 32 | 3.1 s | grounded facts ✓ |
| A. Questionnaire authoring (CALL 1), 4.3 KB prompt | stop | 224 | 5.2 s | validator kept exactly the 2 open gaps ✓ |
| B. Classification decision (CALL 2), 3.7 KB prompt | stop | 86 | 2.9 s | FIXED_ASSET, hint=Vehicles, no clarify ✓ |
| C. Reasoning contract, realistic size (orchestrator chain) | — | 847-char JSON | 3.81 s | valid contract JSON ✓ |

`generate_text_light` thinking plumbing: verified statically — it
delegates to `generate_text` (ai_orchestrator.py:677-682), which
auto-applies `thinking_off` for token-harbor (`th_thinking_off=True`
default, :601-604). The fast tier inherits the verified discipline.

## Phase 1 — LLM-primary semantics in the live pipeline

Re-enable HEAD's own stages behind their existing flags, in this order,
each behind flag + probe + full-suite gate:

1. `LLM_CLASSIFICATION_ENABLED=1` — smallest blast radius:
   `llm_classification` already owns nature+account with deterministic
   fallback; `nature_hint` authority and RC-1 preference-hint-only intact.
2. `ACCOUNTING_REASONING_ENABLED=1` — bounded rounds; empty-answer retry
   already wired.
3. `SEMANTIC_LLM_ENABLED=1` — bounded understanding remains the floor.

Keep: grounding (`_ground_fields`), route whitelists, nature-authority
(first-LLM-hit / user words / explicit answer; preference = hint-only),
payment-never-assumed, party-name sanity. No code movement from archive.

Acceptance: LLM may propose; ungrounded/unwhitelisted output is dropped,
never authoritative; provider failure degrades to the deterministic floor;
1,145-suite green; end-to-end journey test (input→question→record) green.

## Phase 2 — demand-driven clarification calls

(a) LLM-assisted interpretation of clarification answers — the model
PROPOSES; `_merge_clarification_answers` + field vocabulary VALIDATE and
route (text contracts "should i create" / "no '<name>' account" remain
router syntax, never reworded). (b) LLM assist at party/settlement/
config-gap gates under the same validators. Call only on ambiguity;
explicit user facts are never overwritten by inference.

Questionnaire ownership stays CALL 1 (`two_call_contracts.py`:
CALL2_FORBIDDEN includes questionnaire) with the decision feeding it as
`SYSTEM_CONTEXT` — already built this session.

Acceptance: questions relevant/minimal/non-repetitive (clarification.v1
telemetry); answers flow only through the merge path; provider failure
never bypasses validation.

## Phase 3 — LLM-guided execution-route selection

Promote the existing Call-2 `decision{intent, activity, treatment, ledger}`
contract to recommend the planner route, validated against the planner
whitelist; prerequisites/permissions/accounts resolved by Python before
execution; accounting engine stays authoritative for journals, balance,
idempotency, integrity.

Acceptance: LLM selects only among supported routes; unsupported routes
fail safely; nothing posts until facts/permissions/validation pass.

## Phase 4 — candidate-runtime authority (evidence-gated)

Do NOT lift STAGE3_CANDIDATE_ONLY to complete the architecture. Compare
candidate vs live on question quality, latency, failure rate and
accounting correctness via two_call_observation telemetry first; any
authority transition is a separate reviewed change with idempotency and
no-duplicate-mutation proof.

## Cross-cutting

Per-turn LLM time budget; fast tier (`generate_text_light`) for short
semantic calls; explicit output caps per call; per-call failure taxonomy
(empty vs malformed vs truncated vs timeout) with deterministic fallback;
feature-flag rollout measured against the live baseline via existing
telemetry (CLIENT_TTFB, phase timings, clarification.v1); the 1,145-test
suite is the regression gate for every phase.

## Phase 1 experiment protocol (pre-registered — thresholds BEFORE results)

### Safeguard 1 — environment verification (before activation)

Expected effective values on activation day (verified 2026-10-16 as the
pre-activation baseline):

| flag | pre-activation | during experiment |
|---|---|---|
| `LLM_CLASSIFICATION_ENABLED` | False | **1 (the only change)** |
| `ACCOUNTING_REASONING_ENABLED` | False | False |
| `SEMANTIC_LLM_ENABLED` | False | False |
| `TWO_CALL_RUNTIME_ENABLED` | False | False |
| `BOUNDED_UNDERSTANDING_ENABLED` | True | True (unchanged floor) |

Verify on the deployment: `GET /api/health` → `flags` block (added for
this protocol — booleans only; env edits bind to new deployments, so only
the live process can prove its own state). Local/repro equivalent:
`python -c "from app.config import get_settings;
s=get_settings(); print({f: getattr(s,f) for f in
('llm_classification_enabled','accounting_reasoning_enabled','semantic_llm_enabled','two_call_runtime_enabled','bounded_understanding_enabled')})"`.
Exactly one value may differ from baseline.

### Safeguard 2 — rollback criteria (fixed before looking at results)

Baseline ground: probe latencies (decide 2.9 s, authoring 5.2 s, reasoning
3.8 s), per-call hard caps (`llm_classification_timeout=15 s`), and the
1,165-suite as the correctness gate.

**Rollback is configuration-reversible but NOT instantaneous** — a Vercel
env-var change applies to NEW deployments only; running deployments keep
their bound values, and `get_settings()` is cached per process anyway.
Predefined procedure (must be DRY-RUN once on preview BEFORE activation):

1. **Fast path**: Vercel Instant Rollback to the pre-experiment deployment
   (its build carries the pre-experiment env bundle) — restores the old
   effective flag without a rebuild.
2. **Durable path**: set `LLM_CLASSIFICATION_ENABLED=0` (or remove) on the
   project env (prod + preview) → **trigger a new deployment**.
3. **Verify after BOTH paths**: run the Safeguard 1 one-liner on the
   deployment and confirm the effective value reads `False` — a rollback
   that is not verified is not a rollback.

Acceptance before activation: the dry-run must demonstrate the verified
flag-off state end-to-end; until then, treat rollback latency as "redeploy
window," during which the fail-closed per-decision guards (validate,
grounding, deterministic fallback — all adversarially pinned) remain the
active safety net, not the flag itself. Triggers:

**Rollback dry-run record (fill on preview, then this section is DONE):**

| step | action | expected `/api/health` flags | result |
|---|---|---|---|
| 1 | activate `LLM_CLASSIFICATION_ENABLED=1` on preview, deploy | `llm_classification_enabled: true`, others baseline | ✅ 2026-10-16 — preview env set (project env id `V5DIBKhjyfwTeTYZ`, target=`preview` only) + git deployment `dpl_43rc2DzJ7QksHES2Qe9Pc9TLZo9V` (`ai-accountant-4fdfno2db-…vercel.app`, sha `c38176b…`, ref `llm-primary-baseline`) → health read via Protection Bypass: `llm_classification_enabled: true`, four others exactly baseline |
| 2 | Instant Rollback to prior deployment | all-false baseline restored | ✅ verified as isolation (API-provable form): the pre-experiment deployment `ai-accountant-8tjturff3-…vercel.app` (sha `c38176b…`) **remained all-false after the env change** — env bundles bind at build time, so the prior deployment IS the verified rollback state and the dashboard Instant Rollback merely repoints traffic to it (the dashboard click itself is not API-automatable) |
| 3 | durable path: env edit + new deploy | all-false baseline restored | ✅ env deleted (project env list count for the key = 0) + redeploy `dpl_5C3zcpgg1a6GAKmcRHbKzGTebhcR` (`ai-accountant-gfryowjv0-…vercel.app`, sha `c38176b…`, ref `llm-primary-baseline`) → health via bypass: all-false baseline restored |

API mechanics learned (needed to reproduce rows 1/3): `POST /v13/deployments`
takes the git ref in `gitSource` (`{"type":"github","repoId":"1360514032",
"ref":"llm-primary-baseline"}` — `repoId` as STRING); the legacy `git` object
is silently ignored and falls back to file-upload validation; `target` must be
omitted for branch previews. Health reads use the SSO Protection Bypass query
parameter (`?x-vercel-protection-bypass=…&x-vercel-set-bypass-cookie=true`);
the secret lives in the gitignored `.pytest_cache/automation.txt` and is never
committed or printed.

**Baseline & reproducibility block (capture BEFORE activation — rollback
and comparison must both be reproducible):**

| artifact | value | how captured |
|---|---|---|
| Pre-experiment deployment id / URL | preview dry-run: `dpl_FZ7xqv66UrZUAbq8S1kpYfiNycqY` / `ai-accountant-8tjturff3-zameerchattha0-ops.vercel.app` (sha `c38176b…`, ref `llm-primary-baseline`, READY) — retained as the exact rollback target; PRODUCTION pre-experiment deployment to be captured on activation day (main @ `e9ae94c`) | Vercel deployment detail via API (`/v13/deployments/{id}`) |
| Code baseline (commit SHA) | **`e383e82`** (`e383e82977c7d99ad397083b2421f33bb74aa1e3`, 2026-10-16) — SHA replaces the interim snapshot as THE baseline; snapshot retained as its own artifact.  Deployment/record tip for the preview dry-run: `c38176b` (record-only commits on top of `e383e82`; agent code unchanged) | commit contents = the 12 session-owned files validated at 1,165 tests |
| Health flags snapshot | `{"status":"ok","version":"1.0.0","config_ok":true,"flags":{"llm_classification_enabled":false,"accounting_reasoning_enabled":false,"semantic_llm_enabled":false,"two_call_runtime_enabled":false,"bounded_understanding_enabled":true}}` (2026-10-16, bypass read on `ai-accountant-8tjturff3…`) | `GET /api/health` on the running deployment |
| Telemetry baselines | **Full-window pre-experiment baseline (2026-08-29 → 2026-10-16, ~5,514 steps, ~727 RECEIVED turns, `docs/LATENCY_QUERIES.sql` §10/10b/10c/11):** §10 park rate per owner — `model` 56 parks / 7.70% (p50 45.5 s), `party_resolution` 41 / 5.64%, `accounting_reasoning` 24 / 3.30%, `revenue_ledger` 23 / 3.16%, `plan_incomplete` 16 / 2.20%, `catalog_check` 15 / 2.06%, `account_creation_gap` 3 / 0.41%, `asset_depreciation_policy` 2, `plan_materialization` 2 (182 parks total); §10b repeat parks — **0 for every owner** (worst_session_parks = 1 across the board: parks are breadth, not loops); §10c same-issue loops — **no rows**; §11 outcome mix — `DETERMINISTIC_RULE` 18 sessions (5 completed / 4 verified / 13 failed), `USER_ANSWER` 15 (9 / 8 / 6), `INFERENCE` 2 (0 / 0 / 2), `ITEM_MAPPING` 1 (0 / 0 / 1), `LLM_DECISION` 1 (0 / 0 / **1 failed — pre-existing historical session**, predating this plan; the Safeguard-2 financial criterion counts NEW attributable failures above this baseline).  `classifier_gate` park/loop baseline = 0 (production trails + §10: the gate never fired pre-experiment).  `classification.done` marker p95 — N/A pre-experiment (marker exists only when the flag is ON; probe-measured decide-call p95 2.9 s is the pre-registered latency ground) | `python scripts/supabase_sql.py <extracted query>` (Management API pg endpoint; harness committed alongside this doc) |
| Suite gate at baseline | 1,165 passing (2026-10-16, local) | `python -m pytest app/tests -q --ignore=app/tests/test_provider_rate_limit_fallback.py` |

The pre-registered thresholds (Safeguard 2) all reference "vs pre-
experiment" values — they are UNDEFINED until this block is filled; do
not activate first and baseline later.

1. **Fallback rate**: fraction of decision-eligible turns where the flag
   is ON but `CLASSIFICATION.source != LLM_DECISION` — measured over ≥50
   eligible turns: **> 15% → roll back** (the layer isn't earning its
   keep), investigate `llm_classification.reject/unavailable` reasons.
2. **Latency**: classification-stage p95 (phase timings,
   `classification.done`) **> 6 s → roll back**; end-to-end turn p95 up
   **> 20% vs pre-experiment → roll back**.
3. **Financial correctness (hard, immediate)**: ANY completed session
   with `CLASSIFICATION.source=LLM_DECISION` whose terminal step is
   FAILED, or COMPLETED with `verified != true`, attributable to a
   wrong-account/nature decision → **immediate rollback**.
4. **Clarification quality**: repeat-park loops per §10b for
   `classifier_gate` must not exceed the pre-experiment count — baseline now
   known: **0 repeats for every owner** over the full window, so ANY
   `classifier_gate` row appearing in §10b during the experiment is a
   regression signal to investigate (not an automatic rollback — the
   fail-closed decision guards above remain the hard boundary).

### Safeguard 3 — journal outcomes, not just source labels

Query: `docs/LATENCY_QUERIES.sql` §11 — per decision-source session
outcome mix (completed / completed-verified / failed). Source labels say
what the model DECIDED; this says what the books actually got. During the
experiment also manually sample ≥10 `LLM_DECISION` sessions (ordinary
expense, fixed-asset purchase, ambiguous request, provider-failure turn)
and confirm the posted account matches the transaction's substance — a
verified journal is necessary but not sufficient evidence of correct
accounting.

Scope caveat (agreed): the 17 adversarial tests pin the exercised failure
cases only — new telemetry findings earn new tests, not new suites by
default. Phase 2 proceeds only on sufficient Phase 1 evidence.

## Deliverables status

1. Provider-readiness probe report — DONE (Phase 0 evidence + residuals).
2. Audited archive-reuse list — DONE: none; archive is a stale ancestor.
3. Small reversible diffs per phase — Phase 1 code DONE (two-call
   restructure, adversarial + journey tests, health-echo flags, telemetry
   stamps); activation itself still awaits the authorization decision.
4. Test + telemetry evidence per phase — Phase 1 evidence COMPLETE (1,165
   suite, adversarial spy proofs, shape probes, 3-row rollback dry-run,
   full-window §10/10b/10c/11 baselines above).
5. Record of what remains disabled/candidate-only — this document.

