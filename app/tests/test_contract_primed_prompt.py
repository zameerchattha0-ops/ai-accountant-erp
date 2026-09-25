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
* size: base stays under the legacy 11,500-char latency ceiling (measured
  10,799) and the contract-primed production shape is pinned under
  PRIMED_CEILING (measured 13,980 = +3,181 chars / ~795 input tokens —
  deliberately accepted to eliminate a measured 6-11s rejection round).
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

BASE_CEILING = 11_500  # legacy pinned budget (contracts NOT passed — unchanged)
PRIMED_CEILING = 14_500  # measured 13,980 on 2026-09-23; ~4% headroom

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

