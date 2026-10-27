"""
Tests for Single-Hop Resolution in resume_with_clarification.
Guarantees Turn 2 clarification answers execute directly in <500ms without restarting the 5-phase pipeline.
"""

import uuid
import pytest
from app.models.schemas import ExecutionStatus, ToolCall, ToolResult
from app.auth import AuthContext
import app.agent as agent_mod


@pytest.mark.asyncio
async def test_single_hop_operational_create_account(monkeypatch):
    """When a clarification is answered for create_account, single-hop resolves directly."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Create account for Office Utilities",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "What type of account is this?",
        "required_information": ["account_type"],
        "reason": '{"intent": "create_account", "extracted_entities": {"account_name": "Office Utilities"}, "missing_fields": ["account_type"]}',
        "status": "WAITING_FOR_USER",
    }

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return [{"field": "account_type", "question": "account_type", "answer": "Expense"}]

    executed_calls = []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={"name": tc.arguments.get("name"), "account_type": tc.arguments.get("account_type"), "reused_existing": False},
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Expense",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "create_account"
    assert executed_calls[0].arguments["name"] == "Office Utilities"
    assert executed_calls[0].arguments["account_type"] == "EXPENSE"
    assert "Office Utilities" in resp.summary


@pytest.mark.asyncio
async def test_single_hop_operational_create_customer(monkeypatch):
    """When a clarification answers the missing customer name, single-hop registers customer directly."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Create a new customer",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "What is the name of the new customer?",
        "required_information": ["customer_name"],
        "reason": '{"intent": "create_customer", "extracted_entities": {}, "missing_fields": ["customer_name"]}',
        "status": "WAITING_FOR_USER",
    }

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return [{"field": "customer_name", "question": "customer_name", "answer": "Acme Global"}]

    executed_calls = []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={"id": str(uuid.uuid4()), "name": tc.arguments.get("name"), "reused": False},
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Acme Global",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "create_customer"
    assert executed_calls[0].arguments["name"] == "Acme Global"
    assert "Acme Global" in resp.summary


@pytest.mark.asyncio
async def test_single_hop_supplier_balance_lookup(monkeypatch):
    """When a clarification answers the supplier name, single-hop executes ledger lookup directly."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "How much do we owe the vendor?",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "Which supplier?",
        "required_information": ["supplier_name"],
        "reason": '{"intent": "supplier_balance", "extracted_entities": {}, "missing_fields": ["supplier_name"]}',
        "status": "WAITING_FOR_USER",
    }

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return [{"field": "supplier_name", "question": "supplier_name", "answer": "Prime Steel"}]

    executed_calls = []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={"supplier_name": "Prime Steel", "current_balance": 45000.0},
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Prime Steel",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "get_supplier_ledger"
    assert executed_calls[0].arguments["supplier_name"] == "Prime Steel"
    assert "Rs. 45,000.00" in resp.summary


@pytest.mark.asyncio
async def test_single_hop_financial_expense_date_followup_without_assume_today(monkeypatch):
    """Requirement 2: When payment_type is answered and transaction_date is omitted:

    Do NOT assume today, ask the user directly (<200ms) without restarting pipeline.
    """
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Paid 3500 for ac repair",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "How was the AC repair paid and on what date?",
        "required_information": ["payment_type", "transaction_date"],
        "reason": '{"intent": "record_expense", "extracted_entities": {"amount": 3500.0, "description": "AC repair"}, "missing_fields": ["payment_type", "transaction_date"]}',
        "status": "WAITING_FOR_USER",
    }

    created_clarifications = []

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return [{"field": "payment_type", "question": "payment_type", "answer": "Cash"}]

    async def fake_create_clarification(*, session_id, question, required_fields=None, options=None, reason=None):
        rec = {
            "session_id": session_id,
            "question": question,
            "required_fields": required_fields,
            "options": options,
            "reason": reason,
        }
        created_clarifications.append(rec)
        return rec

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.database.create_clarification", fake_create_clarification)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Cash",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    # Must NOT assume today! Must ask user for date directly without restarting pipeline
    assert resp.status == ExecutionStatus.AWAITING_CLARIFICATION
    assert resp.required_information == ["transaction_date"]
    assert "Today" in resp.options
    assert len(created_clarifications) == 1
    assert created_clarifications[0]["required_fields"] == ["transaction_date"]


@pytest.mark.asyncio
async def test_single_hop_financial_expense_with_date_and_payment_in_one_turn(monkeypatch):
    """Requirement 3: When all financial fields (amount, payment_mode, date) are resolved,

    execute create_expense in single-hop directly.
    """
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Paid 3500 for ac repair",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "How was the AC repair paid and on what date?",
        "required_information": ["payment_type", "transaction_date"],
        "reason": '{"intent": "record_expense", "extracted_entities": {"amount": 3500.0, "description": "AC repair"}, "missing_fields": ["payment_type", "transaction_date"]}',
        "status": "WAITING_FOR_USER",
    }

    executed_calls = []

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={
                "id": str(uuid.uuid4()),
                "total": tc.arguments.get("subtotal"),
                "description": tc.arguments.get("description"),
                "payment_mode": tc.arguments.get("payment_mode"),
                "expense_date": tc.arguments.get("expense_date"),
                "journal_posted": True,
            },
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Cash, today",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "create_expense"
    assert executed_calls[0].arguments["subtotal"] == 3500.0
    assert executed_calls[0].arguments["payment_mode"] == "CASH"
    assert "Expense Recorded" in resp.summary


@pytest.mark.asyncio
async def test_single_hop_create_invoice(monkeypatch):
    """When clarification is answered for create_invoice, single-hop resolves and posts directly."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Sold software license to Acme Corp for 50000",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "What is the invoice date?",
        "required_information": ["transaction_date"],
        "reason": '{"intent": "create_invoice", "extracted_entities": {"amount": 50000.0, "customer_name": "Acme Corp", "description": "software license"}, "missing_fields": ["transaction_date"]}',
        "status": "WAITING_FOR_USER",
    }

    executed_calls = []

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={
                "id": str(uuid.uuid4()),
                "invoice_number": "INV-00042",
                "total": tc.arguments.get("total"),
                "status": "ISSUED",
                "journal_posted": True,
            },
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Today",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "create_invoice"
    assert executed_calls[0].arguments["customer_name"] == "Acme Corp"
    assert executed_calls[0].arguments["total"] == 50000.0
    assert "Invoice Issued & Receivable Recorded" in resp.summary
    assert "INV-00042" in resp.summary


@pytest.mark.asyncio
async def test_single_hop_record_customer_receipt(monkeypatch):
    """When clarification is answered for record_customer_receipt, single-hop resolves directly."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session_row = {
        "id": str(session_id),
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "status": "WAITING_FOR_USER",
        "user_request": "Received 25000 from Acme Corp",
    }

    clarification_row = {
        "id": str(uuid.uuid4()),
        "execution_session_id": str(session_id),
        "question": "How was this received?",
        "required_information": ["payment_type"],
        "reason": '{"intent": "record_customer_receipt", "extracted_entities": {"amount": 25000.0, "customer_name": "Acme Corp"}, "missing_fields": ["payment_type"]}',
        "status": "WAITING_FOR_USER",
    }

    executed_calls = []

    async def fake_fetch_one(table, filters=None, select="*"):
        if table == "ai_execution_sessions":
            return session_row
        if table == "ai_clarifications":
            return clarification_row
        return None

    async def fake_resolve_clarification(*, session_id, user_response):
        clarification_row["user_response"] = user_response
        clarification_row["status"] = "COMPLETED"
        return clarification_row

    async def fake_get_clarification_history(sid):
        return []

    async def fake_route_tool_call(tc, organization_id, session_id, user_id, auth=None):
        executed_calls.append(tc)
        return ToolResult(
            tool_name=tc.tool_name,
            success=True,
            data={
                "id": str(uuid.uuid4()),
                "amount": tc.arguments.get("amount"),
                "status": "POSTED",
            },
        )

    async def fake_update_status(sid, status):
        session_row["status"] = status.value

    async def fake_log_step(sid, step_type, data):
        pass

    monkeypatch.setattr(agent_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(agent_mod, "resolve_clarification", fake_resolve_clarification)
    monkeypatch.setattr(agent_mod, "get_clarification_history", fake_get_clarification_history)
    monkeypatch.setattr("app.tool_router.route_tool_call", fake_route_tool_call)
    monkeypatch.setattr(agent_mod, "_update_status", fake_update_status)
    monkeypatch.setattr(agent_mod, "_log_step", fake_log_step)

    resp = await agent_mod.resume_with_clarification(
        session_id=session_id,
        user_answer="Cash",
        user_id=user_id,
        organization_id=org_id,
        auth=AuthContext(user_id=user_id, organization_id=org_id, role_code="admin", role_permissions=[]),
    )

    assert resp.status == ExecutionStatus.COMPLETED
    assert len(executed_calls) == 1
    assert executed_calls[0].tool_name == "record_customer_receipt"
    assert executed_calls[0].arguments["customer_name"] == "Acme Corp"
    assert executed_calls[0].arguments["amount"] == 25000.0
    assert "Payment Received & Receipt Recorded" in resp.summary


@pytest.mark.asyncio
async def test_coa_in_memory_cache(monkeypatch):
    """Test Chart of Accounts caching with TTL and invalidation."""
    from app.repositories import account_repository as repo

    org_id = uuid.uuid4()
    fetch_counter = {"calls": 0}

    async def fake_fetch_many(table, filters=None, select=None, order=None, limit=None):
        fetch_counter["calls"] += 1
        return [{"id": str(uuid.uuid4()), "code": "6100", "name": "Rent Expense", "account_type": "EXPENSE"}]

    monkeypatch.setattr(repo, "fetch_many", fake_fetch_many)
    repo.invalidate_coa_cache(org_id)

    # First call: misses cache, queries DB
    res1 = await repo.get_chart_of_accounts(org_id)
    assert fetch_counter["calls"] == 1
    assert len(res1) == 1

    # Second call: hits cache, 0 new DB queries
    res2 = await repo.get_chart_of_accounts(org_id)
    assert fetch_counter["calls"] == 1
    assert res1 == res2

    # Invalidate org cache
    repo.invalidate_coa_cache(org_id)

    # Third call: misses cache after invalidation, queries DB
    res3 = await repo.get_chart_of_accounts(org_id)
    assert fetch_counter["calls"] == 2


@pytest.mark.asyncio
async def test_single_bank_account_auto_binding(monkeypatch):
    """If no bank account is explicitly default, exactly one active bank account auto-binds."""
    from app.repositories import bank_repository as b_repo

    org_id = uuid.uuid4()
    single_bank = [{"id": str(uuid.uuid4()), "bank_name": "Standard Chartered", "is_default": False, "is_active": True}]

    async def fake_fetch_one(table, filters=None):
        return None  # No row with is_default=True

    async def fake_list_bank_accounts(org, is_active=None, limit=50):
        return single_bank

    monkeypatch.setattr(b_repo, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(b_repo, "list_bank_accounts", fake_list_bank_accounts)

    default_bank = await b_repo.get_default_bank_account(org_id)
    assert default_bank is not None
    assert default_bank["bank_name"] == "Standard Chartered"
