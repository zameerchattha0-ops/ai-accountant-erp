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

**Option A finding (2026-10-16, live probes, deployment `dpl_ML6VDxne…`):**
criterion 2's operand is ambiguous — `classification.done` is the FULL
stage (DB hint resolution + LLM consult), not the decide CALL the 2.9 s
ground measured.  Live cold-start turns measured 7.4 / 10.2 / 12.0 s for
the stage while the LLM decision was successfully used
(`account_source=LLM_DECISION`).  Before activation, Option A must collect
warm-turn stage p95 and GPT must pin whether 6 s applies to the stage or
the call — the threshold itself was not changed unilaterally.

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

