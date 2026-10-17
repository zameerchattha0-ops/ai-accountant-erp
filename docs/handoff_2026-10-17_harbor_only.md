# HANDOFF — 2026-10-17 — PROVIDER CUT: TOKEN HARBOR ONLY

Commit `4533147` on `llm-primary-baseline` (== `main`, pushed; Vercel
production deployment triggered).

## Directive

REMOVE Qwen + Gemini from EVERY request path; every request (text, tools,
vision) goes to Token Harbor models.

## Evidence (why)

- Production sale session `19b2c1c4` ("SELL 2 CHAIRS TO GETA LTD FOR
  54000") FAILED at stage `agent_execute`: HTTP 400, cloudflare HTML body,
  `APIError(code=400)` — the Gemini hop's uncontrolled failure mode
  (generic code path, no provider isolation).
- Every Qwen model on this workspace answers HTTP 403
  `AccessDenied.Unpurchased` (measured 2026-10-02) — the Qwen chain was
  dead weight that could only ever fail-expensively behind healthy
  providers.

## What changed (code)

- `app/ai_orchestrator.py`
  - `_candidate_providers` offers ONLY the measured Harbor chains:
    text/tools `th_text_chain_list` (deepseek-v4.1-flash:free [thinking
    OFF] → mimo-v2.6-flash:free → mimo-v2.5:free); vision
    `th_vision_chain_list` (mimo → deepseek-v4.1-flash:free).
  - `text_chain` / `tier_first` params remain signature-compatible but are
    IGNORED (requested tier chains name Qwen models — never reachable).
  - `_get_qwen` / `_get_gemini` are now unconditional refusals (fail
    honestly, never resurrect a dead provider).
  - `/api/ai/providers` reports the Harbor chain only; fallback "none".
- `app/tests/test_orchestrator_tier_first.py` — rewritten to pin the new
  contract (order, no qwen/gemini in ANY mode, refusal builders, unentitled
  drop still works). Full suite: **1197 passed**.

## State / open items

- Vercel env vars `QWEN_API_KEY/QWEN_BASE_URL/QWEN_MODEL/GEMINI_*` still
  exist on the deployment — INERT (nothing reads them for dispatch; the
  only blocked deletion: stored `vcp_` token in `.pytest_cache/VERCEL.txt`
  is expired). `QWEN_TEMPERATURE`/`QWEN_MAX_OUTPUT_TOKENS` must be KEPT:
  the Harbor transport (qwen_client) reads them for payload building.
- Local uncommitted unrelated file: `frontend/src/app/welcome/page.tsx`
  (modified) + `frontend/src/components/hero/NavyHero.tsx` (untracked) —
  left alone.
- Live verification of the sale path after this deploy:
  `.pytest_cache/_sale_verify_20261017.json` (script
  `scripts/_sale_verify_20261017.py`, re-runnable).

## Follow-up commit `4217a10` (2026-10-17) — plan_incomplete dead-end

Production session `7d46349f` (UI turn, WAITING_FOR_USER) exposed three
stacked defects on the continuation-planning path; all three fixed:

- **C** `app/reasoning.py` — `item_line_details` now DERIVES the missing
  half (unit price = amount/qty, qty = amount/price) as
  DETERMINISTICALLY_RESOLVABLE instead of raising a phantom gap.
- **B** `app/agent.py` card — routes REQUIREMENT_ANALYSIS `open_questions`
  into the question; the "nothing is missing, please resend" dead-end copy
  survives only for the truly-empty case (5939bf30).
- **A** `app/agent.py` — ONE escalated `_continue_lookup_only_plan` round
  (evidence reused, no re-query, telemetry `lookup_continuation_retry_result`)
  demands the financial write when the first continuation proposes only
  party-master steps; second failure falls through to the fixed card.

**Production verification (post-deploy, both paths):**
- API probe session `1431b9a5` — COMPLETED / VERIFIED "Credit sale and
  receivable recorded" (4 turns, was 7).
- USER's own UI re-run session `e45a2807` — REQUIREMENT_ANALYSIS shows
  `item_line_details: DETERMINISTICALLY_RESOLVABLE, detail "unit price
  27,000.00 derived from amount 54,000.00 / quantity 2 for 'CHAIRS'",
  open_questions: []`; PLAN_MATERIALIZATION built
  `create_invoice(items: qty 2 × unit_price 27000)`; EXECUTING →
  **COMPLETED, verified=true** — no plan_incomplete park, no dead-end card.
- Watch-item (pre-existing, separate): CLASSIFICATION labelled the turn
  `OPERATING_EXPENSE` while RE_EVALUATION merged `GOODS` — nature-label
  disagreement worth a look; the invoice path executed correctly regardless.

