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

## Tests

* `app/tests/test_two_call_runtime.py` — runtime loop boundaries.
* `app/tests/test_two_call_flag_gating.py` — flag ON/OFF, no-fallback,
  no-mutation at the agent level.
* `app/tests/test_two_call_fixtures.py` — §26 fixture matrix (E1/E2/A1/A2/
  R1/R2/P1/P2/C1 + ambiguity/missing-entity/evidence/needs fixtures).
* Stage 1 contracts: `app/tests/test_two_call_contracts.py`; Stage 2
  observation: `app/tests/test_two_call_observation.py`.
