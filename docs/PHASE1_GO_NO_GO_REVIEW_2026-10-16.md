# Phase 1 go/no-go review — LLM-primary classification experiment
_Dated 2026-10-16. Companion to `LLM_PRIMARY_IMPLEMENTATION_PLAN.md` (the
pre-registered protocol). This review changes NO threshold; it only fills the
operands the plan itself declared "undefined until the baseline block is
filled" — done before any experiment data has been observed, so the
pre-registration property is preserved._

## 1. Gate status (self-verified, not just reported)

| gate | evidence | status |
|---|---|---|
| Rollback dry-run (3 rows) | plan §Safeguard 2 record — deployment ids, bypass health reads | ✅ |
| Telemetry baselines §10/10b/10c/11 | plan Baseline block; `scripts/supabase_sql.py` re-runnable | ✅ |
| Baseline branch tip | `origin/llm-primary-baseline` = `3785952`; commit re-inspected: 3 files, **secret-scan of diff clean (0 hits)**, 0 `_pending_` markers | ✅ |
| Baseline branch merged to `origin/main` | intentionally NOT merged — `origin/main` = `e9ae94c` (production), untouched | by design (see §5) |
| `LLM_CLASSIFICATION_ENABLED` outside preview | no authorization granted | ⛔ pending |

## 2. Frozen thresholds (verbatim from the plan — operands now instantiated)

| # | criterion | rollback line | operand source |
|---|---|---|---|
| 1 | fallback rate over ≥50 decision-eligible turns | observed > 15% | pre-registered; eligible-turn mix now measured (§4) |
| 2 | classification-stage p95 (`classification.done`) | > 6 s | probe ground: decide p95 2.9 s |
| 2b | end-to-end COMPLETED-turn p95 | > 20 % above baseline → **> 76.8 s** | measured baseline §3 (n=14, small-sample caveat) |
| 3 | financial correctness (hard) | ANY new `LLM_DECISION` session FAILED or unverified, attributable to wrong account/nature | baseline contains **1 pre-existing failed `LLM_DECISION` session** — counts as pre-existing, not experiment-attributable |
| 4 | `classifier_gate` repeat-park loops (§10b) | any `classifier_gate` row in §10b (baseline = 0 for every owner) | regression signal → investigate; fail-closed guards remain the hard boundary |

## 3. Latency operands captured (§2, full window)

`COMPLETED` p50 25.8 s / **p95 64.0 s (n=14)** — criterion 2b baseline;
`FAILED` p95 126.5 s (n=25); `AWAITING_CLARIFICATION` p95 101.1 s (n=182);
`CLASSIFICATION` marker p50 13.7 s / p95 49.6 s (n=456, deterministic-era
marker — NOT the LLM call; LLM decide-call probe p95 2.9 s is the flag-ON
ground). The n=14 completed-turn sample is thin: 2b is recorded as an
operational guardrail, and the review explicitly does not treat a single
2b breach as fraud-evidence — it triggers investigation with §11 context.

**Frozen measurement contract for criterion 2 (pinned 2026-10-16 by GPT
review — before p2–p4 scoring, thresholds unchanged):**

| item | decision |
|---|---|
| primary metric | classification-stage wall-clock latency |
| start boundary | entry into the classification stage |
| end boundary | the corresponding `classification.done` event |
| included | all elapsed time inside that stage, incl. model call + stage overhead |
| excluded | unrelated work before/after the classification stage |
| threshold | p95 > 6 s → rollback (UNCHANGED) |
| separate guard | end-to-end turn p95 up > 20% vs pre-experiment baseline → rollback |

The 2.9 s decide-call probe is **diagnostic only** — never the operand.
Operational formula (revised 2026-10-16 after finding the results-mirror
`timings` dict gets OVERWRITTEN by later classification passes — a ping
turn showed mirror `classification.done`=140.5 s vs its CLASSIFICATION
step at 13.0 s; `ai.execution_steps` is therefore authoritative):
`stage_ms = CLASSIFICATION_step.elapsed_ms − PLANNING_step.elapsed_ms`
(both from `input_summary.elapsed_ms`, ms since session start; the
PLANNING step is written at planner completion = hoist-stage entry, the
CLASSIFICATION step at `classification.done`).  Sessions missing either
step are reported as UNMEASURED, never silently dropped.  First two
measurable flag-ON turns: 2.8 s and 4.9 s (both < 6 s; n=2 — NOT a p95).
Cold and warm observations are recorded SEPARATELY; the acceptance p95 is
computed over the full eligible-turn population as measured — any
cold-start exclusion would require explicit pre-scoring justification and
is NOT in force.

**Option A finding (2026-10-16, live probes, deployment `dpl_ML6VDxne…`):**
criterion 2's operand was ambiguous — `classification.done` is the FULL
stage (DB hint resolution + LLM consult), not the decide CALL the 2.9 s
ground measured.  Live cold-start turns measured 7.4 / 10.2 / 12.0 s for
the stage while the LLM decision was successfully used
(`account_source=LLM_DECISION`).  These are WARNING SIGNALS, not a p95
result: n=3 cold observations cannot establish the required percentile.
Per the frozen contract above they are retained in the cold bucket and the
warm population will decide.

## 4. Sample-size determination (how much traffic the experiment needs)

Decision-eligible turns = turns whose intent matches the CALL 2 gate
(expense-family purposes; the prefill gate restricts to `record_expense`).
Measured planner-turn mix (`legacy_intent`, 186 comparable turns):

| intent | share | eligible? |
|---|---|---|
| create_invoice | 31.7 % | no |
| register_fixed_asset | 26.9 % | fixed-asset family (per purpose options) |
| record_cash_purchase | 14.5 % | expense family |
| unknown | 10.8 % | no |
| record_expense | 7.0 % | **yes (narrow gate)** |
| record_expense_payment / credit+purchase / loan / credit_note | 3.2 / 1.6 / 2.2 / 2.2 % | partially |

Turn volume ≈ 727 RECEIVED / 49 days ≈ **14.8 turns/day**. Eligible-rate
bounds: narrow (`record_expense` only) ≈ 1/day; broad (expense family) ≈ 4/day.

| target | n | 95 % CI half-width at p≈0.15 | wall-time (narrow / broad) |
|---|---|---|---|
| pre-registered floor (criterion 1) | 50 | ±9.9 pp | ~7 weeks / ~2 weeks |
| evidence-grade | 100 | ±6.9 pp | ~14 weeks / ~3.5 weeks |

Agreed sampling plan: keep the pre-registered floor at n=50; declare the
run's evidence-grade target n=100; interim reviews at n=25 / 50 / 100;
**dead-traffic rule** — if 0 eligible organic turns appear within 14 days
of activation, the experiment cannot answer criterion 1 and must return to
this review instead of lingering. Safeguard 3's manual sample (≥10
`LLM_DECISION` sessions) is feasible at either n.

### Batch 1 — provisional results (2026-10-16, sandbox, UNSCORED)

Four scripted probes, 20 classify-bearing turns on preview deployment
`dpl_ML6VDxne…` (flag ON, sha `e8790cb`).  **Nothing here is scored**: the
criterion-1 *population* is not yet pinned (below).

- **Stage latency (frozen contract, v2 formula)**: min 923 ms, median ≈3.4 s,
  max 5689 ms — **20/20 under the 6 s line** (n=20 < n=50 floor; not a p95
  result).  Cold-start turns from earlier remain in their own bucket.
- **Provenance**: `account_source=LLM_DECISION` on 14/20; null on 6/20.
  Of the nulls, 2 are payment-intent turns the code never consults the
  layer for (`_PAYMENT_INTENTS` early return, nature null/INFERENCE) —
  excluding those by that code rule: 4/18 = 22% provisional, **against an
  un-pinned population**.
- **Outcomes**: 3 COMPLETED (p1 + p2 verified=true, p3 verified field
  null), 0 FAILED — criterion 3 untriggered.  p4's first run never
  terminated (runner sent `"yes"` for `amount`/`transaction_date` →
  planner `plan_incomplete` loop ×4; runner fixed with numeric defaults +
  `--only`; rerun in progress).
- **Open operand — criterion-1 population (MUST be pinned before n=50)**:
  "decision-eligible turn" is undefined in the plan.  PROPOSAL (code-
  derived, submitted for GPT pinning, nothing adopted): eligible ⇔ intent
  ∉ `_PAYMENT_INTENTS` AND the classification call ran with
  `resolve_account_hints=true`; to make this OBSERVABLE from telemetry,
  the CLASSIFICATION step would also need to carry `execution_plan.intent`
  (small additive stamp, same pattern as `account_source`) — awaiting
  approval, NOT implemented unilaterally.

## 5. Environment and traffic reality (the actual decision)

Verified against production commit `e9ae94c`: `app/llm_classification.py`
and the `llm_classification_enabled` flag EXIST there, and `classify_transaction`
is called from the OLD (pre-hoist) site — the hoisted CALL 2 placement
(`e383e82`) is NOT in production. Consequences:

- The **registered experiment** (hoisted, run-exactly-once-before-questions
  CALL 2) currently exists only on `llm-primary-baseline` deployments.
- Preview deployments have **no organic traffic**; both preview and
  production point at the SAME Supabase project (live books), so any
  scripted probe traffic must run in a sandbox organization only.
- Merging the baseline branch into `origin/main` is therefore not
  bookkeeping — it is the production-code ship that the organic-traffic
  experiment requires.

Options:

| option | what | evidence value | risk |
|---|---|---|---|
| A | preview + scripted sandbox-org probes (~50 eligible turns) | functional dress rehearsal (flag rides, questions grounded, no bad writes) — does NOT satisfy the organic-traffic thresholds | none to production |
| B | authorize merge → production deploy → prod env `LLM_CLASSIFICATION_ENABLED=1` → redeploy → observe organic traffic under §2 thresholds | the registered experiment | ships hoist code + flag to production (rollback path dry-run-proven; fail-closed guards adversarially pinned) |

**Recommendation:** A first (bounded, cheap, no production exposure), then a
separate explicit authorization decision for B. Neither is authorized now.

## 6. Go/no-go checklist

- [x] thresholds frozen before results; [x] baselines captured; [x] rollback
  dry-run verified both paths; [x] health-echo verification surface shipped
  with baseline code; [x] adversarial fail-closed guards pinned (18 tests);
  [x] telemetry re-runnable via committed harness; [x] loop-consolidation
  trigger measured (0 — not supported by data).
- [ ] **user decision:** authorize option A (preview probes), and separately
  option B (merge + production activation). Until both are granted: no flag
  anywhere beyond the cleaned-up preview, `origin/main` untouched.
- [ ] **user decision:** authorize option A (preview probes), and separately
  option B (merge + production activation). Until both are granted: no flag
  anywhere beyond the cleaned-up preview, `origin/main` untouched.

## 7. Criterion-1 population — PINNED (2026-10-17, user pin, before scoring)

The §4 open operand is now closed. Pinned verbatim:

> A probe turn is **decision-eligible** ⇔ `intent ∉ _PAYMENT_INTENTS`
> (classifier.py: `record_expense_payment, record_payment, record_receipt,
> record_bank_transfer, record_supplier_payment, record_customer_receipt,
> record_loan, record_loan_repayment`) **AND** the classification ran with
> `resolve_account_hints=true` (telemetry: `hints_resolved=true` on the
> CLASSIFICATION step).  **Fallback** = `COALESCE(account_source, source) !=
> 'LLM_DECISION'` over the eligible population.  Threshold unchanged: >15% →
> rollback line.

Pinning decisions recorded:

- **Batch 1 is scored retrospectively** under this definition (user pin) —
  its 20 turns predate the `intent` stamp, so the scoring SQL joins the
  PLANNING step's `intent` for those rows.  Nothing is discarded.
- Early returns inside classify that precede the decide layer (confirmed
  `create_account`, named-section USER_ANSWER mappings, catalog product
  matches, item-less requests) remain **eligible-but-fallback** — the
  conservative reading: it can only raise the measured rate, never
  manufacture a pass.
- `hints_resolved=false` turns (proposal/approved paths) are **excluded** —
  the decide layer is unreachable there; counting them would measure the
  planner, not the layer.

Implementation shipped with the pin (additive telemetry, no behavior
change): the CLASSIFICATION step now stamps `intent` (same pattern as
`account_source`), pinned by `TestCriterion1PopulationStamp` in
`test_two_call_restructure.py`.  Shipped as `230fcdf` on
`llm-primary-baseline`; preview redeployed from that sha
(`dpl_6DHCWL2tkRoFd3hmQS2NtssP1KmU`, health: flag ON, four other flags
at baseline).

### Batch 1 — RETRO-SCORED (2026-10-17, pinned definition, provisional)

The 24 recorded Batch-1 sessions (`smart1`+`p4fix` execution ids) scored
via the Appendix SQL with the `pln_intent` fallback join (rows predate
the `intent` stamp):

- **Population**: 20 eligible of 24 CLASSIFICATION turns — excluded:
  2 `record_payment` (intent clause), 2 `hints_resolved=false` (proposal-
  path turns).  Nothing dropped silently.
- **Fallbacks (pinned numerator)**: 3 — `09eb79ab`/`363da006`
  (`register_fixed_asset`, source=USER_ANSWER, account_source NULL) and
  `6baa5313` (`record_expense`, USER_ANSWER NULL — the p1 turn whose
  confirmed `create_account` early-returns before the decide layer: the
  conservative eligible-but-fallback class agreed at pinning).
- **Fallback rate 3/20 = 15.0 %** — exactly AT the rollback line, not
  above it (line is >15 %).  **n=20 < the 50 floor: provisional, NOT a
  criterion-1 result.**
- Stage latency (frozen formula): all 20 eligible < 6 s (0.9–5.7 s).
- Outcomes: 4 COMPLETED (3 verified, `5d62a516` verified=null), 0 FAILED
  — criterion 3 untriggered.  IN_PROGRESS rows are the documented
  non-terminating p4 first-run loops (runner fixed in `a610b5b`).


