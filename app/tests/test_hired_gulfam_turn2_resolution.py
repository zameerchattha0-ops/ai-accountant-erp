import uuid
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent import execute, resume_with_clarification
from app.auth import AuthContext
from app.models.schemas import ExecutionStatus, ToolResult


@pytest.mark.asyncio
async def test_turn1_and_turn2_end_to_end(monkeypatch):
    """
    Simulate the exact user interaction:
    Turn 1: 'WE HAVE HIRED GULFAM AS BD INTERN FROM 1ST OF OCTOBER' -> asks for basic_salary
    Turn 2: '35000' -> successfully creates employee with full_name, date_of_joining, basic_salary, designation
    """
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    created_employees = []

    async def fake_create_employee(organization_id, **kw):
        created_employees.append(kw)
        return {
            "id": str(uuid.uuid4()),
            "employee_code": "EMP-000001",
            "full_name": kw.get("full_name"),
            "date_of_joining": kw.get("date_of_joining"),
            "basic_salary": kw.get("basic_salary"),
            "designation": kw.get("designation"),
        }

    from app.services import employee_service
    monkeypatch.setattr(employee_service, "create", fake_create_employee)

    # Turn 2: resume_with_clarification with snapshot containing Turn 1 context
    snapshot = {
        "intent": "create_employee",
        "extracted_entities": {
            "employee_name": "GULFAM",
            "date_of_joining": "2026-10-01",
            "transaction_date": "2026-10-01",
            "designation": "BD Intern",
        },
        "missing_fields": ["basic_salary"],
    }

    mock_session = {
        "id": session_id,
        "organization_id": org_id,
        "user_id": user_id,
        "user_request": "WE HAVE HIRED GULFAM AS BD INTERN FROM 1ST OF OCTOBER",
        "role": "OWNER",
        "status": "WAITING_FOR_USER",
        "clarification_count": 1,
    }

    auth = AuthContext(user_id=user_id, organization_id=org_id, role_code="OWNER")

    with patch("app.agent.fetch_one", new=AsyncMock(return_value=mock_session)), \
         patch("app.database.resolve_and_fetch_clarifications", new=AsyncMock(return_value=({}, [], snapshot))), \
         patch("app.agent.resolve_clarification", new=AsyncMock()), \
         patch("app.agent.get_clarification_history", new=AsyncMock(return_value=[])), \
         patch("app.agent._get_clarification_snapshot", new=AsyncMock(return_value=snapshot)), \
         patch("app.agent._update_status", new=AsyncMock()), \
         patch("app.agent._log_step", new=AsyncMock()), \
         patch("app.agent.create_execution_result", new=AsyncMock()), \
         patch("app.tool_router.authorize_tool", new=AsyncMock(return_value=True)), \
         patch("app.tool_router.validate_operation", new=AsyncMock(return_value=MagicMock(allowed=True, violations=[]))):

        response = await resume_with_clarification(
            session_id=session_id,
            user_answer="35000",
            organization_id=org_id,
            user_id=user_id,
            auth=auth,
        )

        assert response.status == ExecutionStatus.COMPLETED
        assert response.verification_status == "VERIFIED"
        assert len(created_employees) == 1
        emp = created_employees[0]
        assert emp["full_name"] == "GULFAM"
        assert emp["date_of_joining"] == "2026-10-01"
        assert emp["basic_salary"] == 35000.0
        assert emp["designation"] == "BD Intern"
        assert "/employees" in response.summary
        assert "Successfully registered employee 'GULFAM'" in response.summary
