"""created_by ownership — plan-time rejection + router rebind.

Production incident 2026-09-24 16:30 (session 66d1dbb6): the model emitted
``created_by: "user"`` in a ``record_customer_receipt`` plan.  The NAME
contract accepted the key (the service signature has the parameter), the
plan was approved, and execution died inside the atomic receipt RPC at
``(p_header->>'created_by')::uuid`` — ``22P02 invalid input syntax for type
uuid: "user"`` — surfaced only as the generic failure banner.

Fix under test:
* signatures now derive ``uuid_params`` (value domain from the SAME source
  of truth as the name check) and ``validate_arguments`` rejects non-uuid
  values BEFORE approval;
* ANY model-authored ``created_by`` is rejected at plan time ("omit it");
* ``route_tool_call`` rebinds a supplied value to the authenticated
  executor (or drops it when the tool cannot carry it) — so even a frozen
  approved plan from before the fix can never reach the uuid cast with a
  model value; absent stays absent.
"""

import uuid
from typing import Optional

import pytest

from app.models.schemas import ToolCall, ToolResult
from app.tool_contract import contract_from_callable, validate_arguments
from app.tool_router import route_tool_call
from app.tools import register

ORG = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _receipt_service(
    organization_id,
    *,
    customer_id: uuid.UUID,
    created_by: Optional[uuid.UUID] = None,
    amount: float = 1.0,
):
    ...  # contract fixture only — never called


CONTRACT = contract_from_callable(_receipt_service)


class TestUuidParamsDerivation:
    def test_uuid_annotations_captured(self):
        assert "customer_id" in CONTRACT["uuid_params"]
        assert "created_by" in CONTRACT["uuid_params"]
        assert "amount" not in CONTRACT["uuid_params"]

    def test_optional_uuid_string_annotation_detected(self):
        # future-annotations style: the annotation is source text
        def fn(organization_id, ref: "Optional[uuid.UUID]" = None):
            ...

        contract = contract_from_callable(fn)
        assert "ref" in contract["uuid_params"]


class TestPlanGate:
    def test_model_created_by_rejected_with_omit_message(self):
        args = {"customer_id": str(uuid.uuid4()), "created_by": "user"}
        violations = validate_arguments("record_customer_receipt", args, CONTRACT)
        assert len(violations) == 1
        assert "created_by" in violations[0] and "omit" in violations[0]

    def test_created_by_absent_passes(self):
        args = {"customer_id": str(uuid.uuid4())}
        assert validate_arguments("record_customer_receipt", args, CONTRACT) == []

    def test_non_uuid_value_rejected_before_approval(self):
        violations = validate_arguments(
            "record_customer_receipt", {"customer_id": "INV-000006"}, CONTRACT
        )
        assert len(violations) == 1
        assert "must be a record id (uuid)" in violations[0]

    def test_valid_uuid_passes(self):
        args = {"customer_id": str(uuid.uuid4())}
        assert validate_arguments("record_customer_receipt", args, CONTRACT) == []

    def test_alias_input_not_flagged_as_missing_uuid(self):
        args = {"customer_name": "Alareesh Engineering"}
        violations = validate_arguments(
            "record_customer_receipt",
            args,
            CONTRACT,
            reference_inputs={"customer_id": ("customer_name",)},
        )
        assert violations == []


class _Capture:
    def __init__(self):
        self.calls = []

    def handler(self, slug):
        async def _h(organization_id, **kw):
            self.calls.append(dict(kw))
            return ToolResult(tool_name=slug, success=True, data={"ok": True})

        return _h


async def _route(slug, arguments, *, registered_contract):
    cap = _Capture()
    register(
        slug,
        handler=cap.handler(slug),
        read_only=True,  # skips permission/validator/idempotency; rebind still runs
        description="test double",
        contract=registered_contract,
    )
    result = await route_tool_call(
        ToolCall(tool_name=slug, arguments=arguments),
        organization_id=ORG,
        user_id=USER,
    )
    assert result.success, result.error
    return cap.calls


class TestRouterRebind:
    @pytest.mark.asyncio
    async def test_model_value_rebound_to_executing_user(self):
        contract = contract_from_callable(
            lambda organization_id, created_by=None: None
        )
        calls = await _route(
            "test_cb_rebind_tool", {"created_by": "user"}, registered_contract=contract
        )
        assert calls == [{"created_by": str(USER)}]

    @pytest.mark.asyncio
    async def test_dropped_when_tool_has_no_created_by_param(self):
        contract = contract_from_callable(lambda organization_id: None)
        calls = await _route(
            "test_cb_drop_tool", {"created_by": "user"}, registered_contract=contract
        )
        assert calls == [{}]

    @pytest.mark.asyncio
    async def test_rebound_when_tool_declares_no_contract(self):
        calls = await _route(
            "test_cb_nocontract_tool", {"created_by": "user"}, registered_contract=None
        )
        assert calls == [{"created_by": str(USER)}]

    @pytest.mark.asyncio
    async def test_absent_created_by_not_injected(self):
        contract = contract_from_callable(
            lambda organization_id, created_by=None: None
        )
        calls = await _route(
            "test_cb_absent_tool", {}, registered_contract=contract
        )
        assert calls == [{}]
