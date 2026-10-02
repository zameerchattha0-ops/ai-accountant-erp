"""P0-② (forensic latency report): contract-primed reasoning prompt.

Finding: the reasoning prompt listed tool SLUGS ONLY, so the model composed
argument keys from whatever vocabulary it could see (evidence rows, entity
field names) and the deterministic gate rejected the proposal AFTER a full
generation round — production session 3ea794a0 burned ~10.7s on
``invoice_number`` vs ``invoice_id`` before its rounds were exhausted.

Pinned invariants:
* offered MUTATION tools carry their inspect()-derived contract lines;
* read-only tools carry none (size discipline — never the whole registry);
* only GATE-accepted reference aliases are advertised (``alias->param``);
* the deterministic gate STILL rejects invented names — priming never
  weakens validation;
* ``run_reasoning_loop`` passes the SAME contracts to prompt and gate;
* size: base stays under BASE_CEILING and the contract-primed production
  shape under PRIMED_CEILING.

Ceiling history (measured, never silent):
* 2026-09-23: base=10,799 / primed=13,980 → ceilings 11,500 / 14,500.
* 2026-09-25: base=12,528 / primed=15,709 → ceilings 13,000 / 16,200.
  +1,729 chars (~430 input tokens) from FOUR required instruction blocks:
  settlement-assumption prohibition (cash incident), consolidated 360°
  questionnaire, chart-of-accounts category granularity, and credit/debit
  note impact rules.  Input-side only — generation is unchanged, and the
  static head is byte-identical across rounds so the prefix cache absorbs
  it after round 1.
* 2026-09-28: base=13,655 / primed=17,390 → PRIMED ceiling 17,300 → 17,600
  (base unchanged).  +661 chars / ~+165 input tokens (+1.0%) from the TWO
  payroll mutation tools (Employees Phase 2, migration 086): 317 chars of
  contract lines (run_payroll 148 + pay_employee_salary 167 — the explicit
  account-override parameters) and ~344 chars of slug/offered-tools drift
  measured against the last recorded 16,729.  Input-side only, static head,
  prefix-cached after round 1 — the same shape every earlier raise had.
 * 2026-09-28 (Wave A): base=14,089 / primed=17,824 → ceilings 14,000 → 14,500
  and 17,600 → 18,200.  +434 chars (~+109 input tokens, +0.6% of the primed
  shape) from the Wave A OBSERVATION block — two optional contract lines
  (``decision``, ``prerequisites``) plus the instruction line that pins them to
  canonical values (E:\Qoder\AUDIT_REPORT.md §7 Wave A, §8 gate).  Input-side
  only, static head, prefix-cached after round 1 — same shape as every raise
  above.  HONEST GAP: the fresh generation-latency measurement could NOT be
  taken — the primary provider returned HTTP 429 (free-tier daily cap)
  throughout this change — so re-measuring generation latency on this shape is
  an explicit A→B gate item (AUDIT_REPORT §8), not a claim made here.
 * 2026-09-28 (§12.8): base=14,076 / primed=17,811 (−13 chars each).  The
  UNDEFINED `continuation` event_type was removed from the reasoning contract:
  it existed ONLY in that enum — no intent, tool, service or definition
  anywhere — so the model could never answer it canonically (AUDIT_REPORT
  §12.8).  Shrink only; ceilings unchanged.
 * 2026-10-02: base=14,076 (unchanged) / primed=18,216 (+405 chars, ~+101
   input tokens, +2.3%) from the TWO contracts added to the fixed-asset
   lifecycle tools (dispose_fixed_asset, record_asset_depreciation were
   registered WITHOUT `contract=`, so the contract block never advertised
   them — Copilot code review 2026-10-02).  PRIMED ceiling 18,200 → 18,400
   WITH the required generation-latency measurement: 17,844 ms for this exact
   18.2 KB shape (finish_reason=stop, 2,783 answer chars) inside the same
   30 s/round timeout — produced by scripts/measure_primed_prompt_latency.py.
   Input-side only, static head, prefix-cached after round 1 — same shape as
   every earlier raise.  HONEST GAP: the measurement could NOT be taken on
   the configured primary (qwen3.6-plus answered HTTP 403
   `AccessDenied.Unpurchased` on 2026-10-02 — the model is not eligible on
   this workspace), so the number above comes from the Token Harbor fallback
   that actually served the request; the primary entitlement is a separate
   operator action item.

"""

import json
import uuid

import pytest

from app.accounting_reasoning import (
    PROPOSAL,
    REQUIRED_PROPOSAL_FIELDS,
    ReasoningFacts,
    ReasoningOutcome,
    build_reasoning_prompt,
    preliminary_extraction,
    run_reasoning_loop,
    validate_outcome,
)
from app.tools import list_tools, tool_contracts

BASE_CEILING = 14_500  # measured 14,076 on 2026-09-28 (Wave A observation
# block, then the §12.8 shrink of the undefined `continuation` event_type; the
# ceiling history above records both).  The provider is already measured on the
# contract-primed 17.8 KB prompt inside the same 30 s/round timeout (6-25 s),
# so a 14.1 KB base stays inside the measured envelope.  Raise only with a
# fresh generation-latency measurement — never silently.
PRIMED_CEILING = 18_400  # measured 18,216 on 2026-10-02 (+405 from the two
# fixed-asset contracts added that day — see the ceiling history above) and
# GENERATED in 17,844 ms (finish_reason=stop) inside the 30 s/round timeout,
# measured by scripts/measure_primed_prompt_latency.py.  The previous raise:
# 17,811 on 2026-09-28 (Wave A, ~2.1% headroom); its latency re-measurement
# remains an A→B gate item recorded in E:\Qoder\AUDIT_REPORT.md §8.

MSG = "I received 60000 from FDS Labs Pvt"


def _facts() -> ReasoningFacts:
    return ReasoningFacts(user_request=MSG, preliminary=preliminary_extraction(MSG))


def _proposal_outcome(args: dict) -> ReasoningOutcome:
    """A structurally complete PROPOSAL so only argument names are judged."""
    return ReasoningOutcome(
        status=PROPOSAL,
        proposal={
            "interpretation": "Settle the open receivable from FDS Labs Pvt.",
            "affected_records": ["customer receipt"],
            "accounting_impact": [
                {"account": "Bank", "debit": 60000, "credit": 60000, "reason": "cash in"}
            ],
            "not_affected": [],
            "unresolved_uncertainty": [],
            "tools": [
                {"tool_name": "record_customer_receipt", "arguments": dict(args)}
            ],
            "confirmation": "Record receipt of 60,000 from FDS Labs Pvt?",
        },
        stated_disclosures=list(REQUIRED_PROPOSAL_FIELDS),
    )


class TestContractPrimedPrompt:
    def test_mutation_tool_contract_rendered_from_real_signature(self):
        """The FDS case: invoice_id advertised, invoice_number only as alias."""
        prompt = build_reasoning_prompt(
            _facts(),
            offered_tools=["record_customer_receipt", "search_customer"],
            tool_contracts=tool_contracts(),
        )
        assert "TOOL ARGUMENT CONTRACTS" in prompt
        line = next(
            l for l in prompt.splitlines()
            if l.startswith("  record_customer_receipt:")
        )
        accepted_part = line.split(" [required")[0]
        assert "invoice_id" in accepted_part          # the bindable name
        assert "invoice_number" not in accepted_part  # NOT a parameter ...
        assert "invoice_number->invoice_id" in line    # ... but a gate-accepted alias
        assert "customer_id" in accepted_part
        # Size discipline: read-only tools never get contract lines.
        assert not any(
            l.startswith("  search_customer:") for l in prompt.splitlines()
        )

    def test_no_contracts_passed_prompt_is_unchanged(self):
        """Backward compatibility: without contracts the prompt is byte-shape
        identical to the legacy layout (the archived budget test's basis)."""
        prompt = build_reasoning_prompt(_facts(), offered_tools=list(list_tools()))
        assert "TOOL ARGUMENT CONTRACTS" not in prompt
        assert len(prompt) < BASE_CEILING

    def test_gate_still_rejects_invented_names_after_priming(self):
        """Priming raises first-pass odds; it NEVER weakens the gate."""
        contract = tool_contracts()["record_customer_receipt"]
        # Bindable base: uuid-typed required parameters need a real uuid —
        # the gate's value domain (tool_contract.uuid_params) rejects any
        # non-uuid id exactly as it rejects an invented name.
        base_args = {
            name: (
                str(uuid.uuid4())
                if name in (contract.get("uuid_params") or ())
                else name
            )
            for name in (contract.get("required") or ())
        }

        # The natural phrasing passes: required keys + the DECLARED alias.
        ok = validate_outcome(
            _proposal_outcome({**base_args, "invoice_number": "INV-000005"}),
            offered_tools=("record_customer_receipt",),
            tool_contracts=tool_contracts(),
        )
        assert ok == [], ok

        # A truly invented key is still rejected before confirmation.
        bad = validate_outcome(
            _proposal_outcome({**base_args, "invoice_no": "INV-000005"}),
            offered_tools=("record_customer_receipt",),
            tool_contracts=tool_contracts(),
        )
        assert any("invoice_no" in v for v in bad), bad

    def test_production_prompt_size_budget(self):
        """Measured budget: base unchanged, contract-primed shape pinned.

        2026-09-23 measurement: base=10,799; contract-primed=13,980
        (+3,181 chars / +29.5% / ~795 input tokens, 15 mutation-tool
        contracts of 59 offered tools).  Raise PRIMED_CEILING only with a
        measured generation-latency justification — never silently.
        """
        offered = list(list_tools())
        base = build_reasoning_prompt(_facts(), offered_tools=offered)
        primed = build_reasoning_prompt(
            _facts(), offered_tools=offered, tool_contracts=tool_contracts()
        )
        assert len(base) < BASE_CEILING, len(base)
        assert len(primed) < PRIMED_CEILING, len(primed)
        assert "TOOL ARGUMENT CONTRACTS" in primed
        # The contract block must never evict the prompt's contractual labels.
        for marker in (
            "PRIMARY ACCOUNTING REASONING LAYER",
            "EVIDENCE CATALOG",
            "OFFERED TOOLS",
            "HARD PROHIBITIONS",
            "RESPONSE FORMAT",
        ):
            assert marker in primed

    @pytest.mark.asyncio
    async def test_loop_passes_the_same_contracts_to_prompt_and_gate(self):
        """run_reasoning_prompt wiring: the generation the provider receives
        carries the contract block, and a conforming proposal passes."""
        captured: dict = {}

        class _Provider:
            async def generate_text(self, *, prompt: str = ""):
                captured["prompt"] = prompt
                return json.dumps(
                    {
                        "understanding": {
                            "economic_event": "creation of a customer ledger",
                            "basis": "test double",
                        },
                        "proposal": {
                            "interpretation": "Create the FDS Labs customer ledger.",
                            "affected_records": ["customer"],
                            "accounting_impact": [
                                {"account": "Receivable", "debit": 0, "credit": 0,
                                 "reason": "party registration"}
                            ],
                            "not_affected": [],
                            "unresolved_uncertainty": [],
                            "tools": [
                                {
                                    "tool_name": "create_customer",
                                    "arguments": {"name": "FDS Labs Pvt"},
                                }
                            ],
                            "confirmation": "Create customer FDS Labs Pvt?",
                        },
                    }
                )

        outcome = await run_reasoning_loop(
            ReasoningFacts(
                user_request="Create a customer FDS Labs Pvt",
                preliminary=preliminary_extraction("Create a customer FDS Labs Pvt"),
            ),
            organization_id=uuid.uuid4(),
            orchestrator=_Provider(),
            offered_tools=list(list_tools()),
            tool_contracts=tool_contracts(),
            max_rounds=1,
        )

        assert outcome.status == PROPOSAL
        assert outcome.rounds == 1  # first-pass success: no reject round
        assert "TOOL ARGUMENT CONTRACTS" in captured["prompt"]
        assert "  create_customer:" in captured["prompt"]

