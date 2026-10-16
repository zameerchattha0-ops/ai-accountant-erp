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
1,164-suite as the correctness gate.

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
| 1 | activate `LLM_CLASSIFICATION_ENABLED=1` on preview, deploy | `llm_classification_enabled: true`, others baseline | _pending_ |
| 2 | Instant Rollback to prior deployment | all-false baseline restored | _pending_ |
| 3 | durable path: env edit + new deploy | all-false baseline restored | _pending_ |

**Baseline & reproducibility block (capture BEFORE activation — rollback
and comparison must both be reproducible):**

| artifact | value | how captured |
|---|---|---|
| Pre-experiment deployment id / URL | _pending_ | Vercel deployment detail (retain the exact id rolled back TO) |
| Code baseline (commit SHA) | _pending_ — **interim artifact: `docs/BASELINE_SNAPSHOT_2026-10-16.md`** (diff hash + per-file SHA1s of the exact uncommitted state validated at 1,165 tests) | `git rev-parse HEAD` once committed; until then the snapshot file is the reference |
| Health flags snapshot | _pending_ | `GET /api/health` on the running deployment (four stages false, bounded true) |
| Telemetry baselines (pre-window, e.g. 7 days) | _pending_ | §10 park rate per owner; §10b worst-session/loop counts for `classifier_gate`; §11 outcome mix per decision source; `classification.done` p95; turn p95 |
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
   `classifier_gate` must not exceed the pre-experiment count.

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
3. Small reversible diffs per phase — pending, one phase at a time.
4. Test + telemetry evidence per phase — pending.
5. Record of what remains disabled/candidate-only — this document.

