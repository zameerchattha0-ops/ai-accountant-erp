# Stage 3 — Two-Call Semantic Runtime (candidate-only)

Status: **implemented, flag-gated, NOT authoritative.**
Flag: `TWO_CALL_RUNTIME_ENABLED` (default `false`, fail-closed) — completely
separate from `TWO_CALL_OBSERVATION_ENABLED` (Stage 2).

## Ownership

| Layer | Owns | Never owns |
|---|---|---|
| **Call 1** (`build_intake_prompt`) | semantic intake: understanding, facts (EXPLICIT / SAFELY_INFERRED), missing material facts, user-facing questionnaire, evidence requests | accounting treatment, intent, ledger, prerequisites, proposal — Contract A **rejects** these fields |
| **Python** (`app/two_call_runtime.py`) | deterministic admissibility, evidence acquisition, entity resolution, answer merge, bounded loop, execution **state** | semantic reinterpretation — it never converts a missing fact into a treatment |
| **Call 2** (`build_decision_prompt`) | accounting interpretation: intent, activity, document_nature, treatment, payment_terms, ledger, prerequisites, proposal, rationale, refusal, `needs[]` | user-facing question wording — Contract B has no question surface; `needs[USER_FACT]` routes back through Call 1 |
| **Python (validation)** | Contract A/B validation, proposal engine-compatibility (`accounting_reasoning.validate_outcome`), needs routing, bounded decision attempts | execution — validation never mutates |
| **Accounting Engine** | accounting validity (unchanged, authoritative) | — (not invoked by this path in Stage 3) |

## Flow

```
USER REQUEST
   ↓
CALL 1  (Contract A: understanding/facts/missing/questionnaire/evidence)
   ↓
PYTHON  evidence acquisition · user answers · entity resolution · admissibility
   ↓
CALL 2  (Contract B: decision/prerequisites/proposal/rationale/refusal/needs)
   ↓
PYTHON  Contract B validation · validate_outcome (engine-compatible)
   ↓
STOP BEFORE FINANCIAL MUTATION  →  STAGE3_CANDIDATE_ONLY
```

State machine (§21): `RECEIVED → CALL1_INTAKE → (AWAITING_EVIDENCE |
AWAITING_CLARIFICATION) → CALL1_INTAKE → CALL2_DECISION → CALL2_NEEDS
(EVIDENCE→evidence→CALL1 | USER_FACT→CALL1→questionnaire |
CONFIG_PERIOD→deterministic stop) → DECISION_READY → STAGE3_CANDIDATE_ONLY`.

Bounds: `CALL1_MAX_ROUNDS = 3`, `CALL2_MAX_ATTEMPTS = 2` **and a whole-turn
budget** (`TWO_CALL_RUNTIME_TOTAL_TIMEOUT`, default 60 s, must stay below the
host function timeout). Exhaustion parks on `AWAITING_CLARIFICATION`
(USER_FACT) or fails honestly (`turn_budget_exhausted`) — it never fabricates
and never silently falls back to the monolithic interpretation. The per-call
bound is `min(accounting_reasoning_timeout, remaining turn budget)`.

Question floor: before any park, Call 1's `questions[]` pass the SHIPPED
`questionnaire.validate_authored_questions` filter (the same one the
monolithic response site uses) — the 28-field `AUTHORED_FIELDS` vocabulary,
dedupe, and never-re-ask-what-is-already-known (from literal extraction,
intake facts, and answered history fields). Unknown or already-known
entries are dropped, never repaired; when nothing survives the block
disappears and intake is admitted instead of parking on a question Python
already knows the answer to. The intake prompt teaches the vocabulary
because the model can only use field names it has been shown.

## Provider tiering & output bounds

* **Call 1 → fast tier** (`generate_text_light` → `accounting_fast_chain_list`,
  with `tier_first=True`). Intake is mechanical extraction, not accounting
  judgement. Measured live (2026-09-29, shipped Call-1 prompt): the deep
  chain's thinking model spent the whole 2,048-token cap on `reasoning_content`
  and returned EMPTY content (`finish_reason: length`, 8,466 chars of
  reasoning, 0 chars of answer, 20.4 s); with thinking off the same task
  answered in 6.0 s / 520 tokens. `tier_first=True` (opt-in, default false —
  every other caller keeps the shipped primary-first order) skips the Token
  Harbor primary so the fast chain actually leads; when no light entry exists
  (test doubles, older orchestrators) the runtime falls back to
  `generate_text`.
* **Call 2 → deep entry** (`generate_text`): accounting judgement keeps the
  reasoning chain. The tier is config-reversible (`ACCOUNTING_FAST_MODEL_CHAIN=
  standard`).
* **BREVITY is stated in both prompts**: every field is MACHINE-READ — one
  short clause (≤ 120 characters) per prose field, ONE sentence for
  `interpretation`/`confirmation`, no markdown, no restatement. Prose costs
  output tokens that nothing consumes.

## Authority

* **Two-call path is candidate-only in Stage 3.** A validated candidate is
  recorded as an observation/step; no journal, invoice, payment, account,
  customer or supplier is created, and no balance is modified.
* **Legacy path remains authoritative when the flag is OFF** (the default).
  When the flag is ON there is **no hidden fallback**: a candidate failure is
  reported as `FAILED` / `AWAITING_CLARIFICATION`, never re-interpreted by
  the monolithic planner (§18).
* Call 2 never authors user-facing questions (§13).
* Call 1 never decides accounting treatment (§7).
* Approved-plan resumes and batch requests keep their existing paths.

## Live verification (2026-09-29, flag experimentally exercised, never enabled in prod)

* **Empty content root cause — fixed.** The deep chain's first candidate is a
  THINKING model whose `reasoning_content` consumed the whole 2,048-token
  output cap on the intake prompt (finish_reason `length`, 8,466 chars of
  reasoning, 0 chars of answer). Call 1 now runs on the fast chain with
  `tier_first=True`: live Call 1 answers arrived as valid Contract-A JSON in
  11.8–30 s across 20+ turns, zero empty-content results, zero timeouts after
  the change.
* **Question floor — live.** Unknown field names (`asset_capitalization`,
  `gl_account_code`, …) and already-stated fields (`supplier_name`, …) are
  dropped before any park; duplicates collapse (`asset_code` ×3 → ×1);
  remaining parks ask vocabulary fields only.
* **Ownership boundary — live.** With policy asks banned from Call 1, the
  depreciation/code/classification spiral stopped; those belong to Call 2's
  `needs[USER_FACT]` routing.
* **Evidence loop — live.** Call 1 requested 1–5 kinds per round; the shipped
  books layer gathered them (against a seeded org and an empty org), and the
  re-run saw the results. Repeated identical requests hit the per-turn cache.
* **Contract feedback — live.** Rejections were fed back and recovered
  (`questionnaire.text is required` twice pre-fix; a `NOT_REQUIRED` fact state
  once post-fix) — never repaired, never fabricated.
* **Bounds — live.** `intake_rounds_exhausted` (3 rounds) and the 60 s turn
  budget both terminated turns honestly; nothing executed, nothing invented.
* **Not yet observed live: `CANDIDATE_READY`.** The fast-tier model still
  over-asks/over-hunts on richly-specified requests (each turn surfaces ~1–3
  more vocabulary-field asks or another evidence round), so its packets did
  not become admissible within 3 rounds. The candidate path itself is pinned
  by the fixture matrix (E1/A1/A2/P1/P2) and the 140 Stage-3 tests. Treat
  live conclusion quality as a model-choice question for the flag-ON
  decision, not as an architecture defect.

## Tests

* `app/tests/test_two_call_runtime.py` — runtime loop boundaries.
* `app/tests/test_two_call_flag_gating.py` — flag ON/OFF, no-fallback,
  no-mutation at the agent level.
* `app/tests/test_two_call_fixtures.py` — §26 fixture matrix (E1/E2/A1/A2/
  R1/R2/P1/P2/C1 + ambiguity/missing-entity/evidence/needs fixtures).
* Stage 1 contracts: `app/tests/test_two_call_contracts.py`; Stage 2
  observation: `app/tests/test_two_call_observation.py`.
