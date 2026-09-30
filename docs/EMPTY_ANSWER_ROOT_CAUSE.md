# Empty-answer root cause — "The AI provider did not answer in time"

Evidence date: 2026-09-30 (local) · Session `504557ed…` · Request
*"Prchased Car on cash for 4000000"* · Turn: answer **"Yes, create it"**

## Symptom

After the account-treatment question was answered, the UI showed the generic
failure card:

> The AI provider did not answer in time. Nothing was recorded yet. Please send
> your request again — everything you have already told me is kept in this
> conversation.

That text is emitted by exactly one branch: `app/agent.py:3876-3897`
(`_provider_down` gate → `summary` at `:3892`).

## What the recorded step trail says (production)

| time | step | payload (trimmed) |
|---|---|---|
| 20:08:37 | `RECEIVED` | message = "Prchased Car on cash for 4000000" |
| 20:08:39 | `EVIDENCE_PREFETCH` | kinds=[bank_accounts] |
| 20:08:57 | `ACCOUNTING_REASONING` | `status=UNSUPPORTED, provider_failed=true, rounds=1, elapsed_ms=20630` |
| 20:08:58 | `REASONING_DEGRADED` | `reason=provider_unavailable, rounds=1` |
| 20:09:02 | `CLASSIFICATION` | `FIXED_ASSET / HIGH / USER_ANSWER` |
| 20:09:04 | `FAILED` | `reason=provider_unavailable, stage=reasoning, rounds=1` |

Two facts pin the cause before any guess:

* **`elapsed_ms = 20630` — not a timeout.** The round budget is
  `accounting_reasoning_timeout = 90 s` (`config.py`, post-`75a6f20`) and the
  turn budget 135 s. A 20-second failure is an ANSWER-shaped failure, not a
  clock failure. The message is therefore factually wrong for this case.
* **`rounds = 1`, `provider_failed = true`.** The loop returned on the first
  round through the `unparseable_response` path
  (`app/accounting_reasoning.py:1418-1427`): the provider answered, and the
  answer contained no parseable JSON.

The answer-merge itself worked correctly — `PLANNING` recorded
`{transaction_nature: FIXED_ASSET, create_account: Vehicles,
create_parent_name: Accounts Receivable, amount: 4000000, payment_method: CASH}`.
Nothing was lost; only the reasoning round produced no usable content.

## Root cause (measured live, 2026-09-30)

The primary text model is a **thinking** model (`TH_TEXT_MODEL =
deepseek-v4.1-flash:free`) and the client sends
`max_tokens = QWEN_MAX_OUTPUT_TOKENS = 2048` (`ai_orchestrator.py:119`,
`.env:QWEN_MAX_OUTPUT_TOKENS=2048`). On this gateway the output cap is shared
by hidden reasoning (`reasoning_content`) **and** the visible answer. When the
model's reasoning is long, the cap fills before any answer text is emitted:

| payload knob | wall | finish_reason | content | reasoning_content | completion_tokens |
|---|---|---|---|---|---|
| baseline (thinking ON) | **19.7 s** | **`length`** | **0 chars** | 9,358 chars | 2,048 (cap) |
| `enable_thinking=false` | 5.7 s | `stop` | 914 chars | 0 | 224 |
| `thinking={"type":"disabled"}` | 1.9 s | `stop` | 914 chars | 0 | 224 |
| `reasoning_effort="none"` | 20.4 s | `length` | 284 chars (truncated JSON) | 8,826 chars | 2,048 (cap) |
| baseline with `max_tokens=8192` | 50.5 s | `stop` | 1,723 chars | 26,604 chars | 6,528 |

The baseline row is the production failure exactly: `finish_reason=length`,
empty content, 2,048 completion tokens, ~20 s — matching the recorded
`rounds=1, provider_failed=true, elapsed_ms=20630`.

`parse_reasoning_response("")` returns `None` (`accounting_reasoning.py:616-652`),
so the loop reports `provider_failed=True, provider_attempted=True`, the
`_provider_down` gate fires, and the run closes with the timeout wording.

### Why it is intermittent

Whether the answer survives depends on how long the model reasons about the
specific request. Trivial turns ("List my products", 18:56-18:57) fitted inside
the cap and completed; complex ones (asset purchase + account creation + prior
answers) did not. That is the "bursts" pattern observed earlier the same
evening, not a rate limit.

### `reasoning_effort="none"` does not work here

Measured: reasoning still ran (8,826 chars) and the JSON came back **truncated
at 284 chars** — a worse failure mode than an empty answer (partial JSON).
Any fix built on that parameter would be a silent no-op.

## Fix options (all measured, none applied yet)

1. **Disable thinking for the reasoning call** — `enable_thinking: false`
   (5.7 s / 224 tokens) or `thinking: {"type": "disabled"}` (1.9 s / 224
   tokens), both returning valid JSON with 0 reasoning tokens. The client
   already has the plumbing (`qwen_client._payload` sends
   `enable_thinking=False` when the `thinking_off` quirk is set), and the
   Stage-3 two-call runtime already ran Call 1 this way for the identical
   reason. The monolithic reasoning stage never received that treatment.
2. **Raise the output cap for this stage** (e.g. 8,192): works, but 50.5 s and
   3× the tokens — keeps thinking at the cost of the worst latency.
3. **One bounded retry on this specific failure** (`finish_reason=length` with
   empty content) using option 1, plus a truthful user message — "the model
   produced no answer" rather than "did not answer in time".

## Honest caveats

* Probes were run with the local `.env` (TH key, 90 s timeouts, 2,048 cap).
  Production carries no env overrides for these keys, so the code defaults
  apply there — same cap.
* Step data proves the *shape* of the failure (`rounds=1`,
  `provider_failed=true`, 20.6 s). The `finish_reason`/token counters come
  from the live reproductions, which matched the timing and emptiness exactly.
* Server-side structlog is not retrievable on the current Vercel plan, so the
  exact prompt for that turn could not be diffed; the failure was reproduced
  with a same-size prompt instead.
