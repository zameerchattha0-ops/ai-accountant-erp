import sys
sys.path.insert(0, ".")
import asyncio
import uuid

from app.database import fetch_many, fetch_one
from app.conversational_manager import build_intent_progression, synthesize_cumulative_dialogue_intent
from app.tool_router import get_handler, route_tool_call
from app.models.schemas import ToolCall
from app.auth import AuthContext
from app.multi_item_disaggregator import MultiItemDisaggregationResult, DisaggregatedLineItem


async def verify_flow():
    orgs = await fetch_many("organizations", filters={}, limit=1)
    org_id = uuid.UUID(orgs[0]["id"])
    print(f"Testing with Organization: {orgs[0]['name']} ({org_id})")

    # 1. Synthesize multi-item composite statement
    msg = (
        "Paid 250,000 today: 150,000 for office rent, 30,000 electricity bill, "
        "and bought an executive laptop for 70,000 via Meezan Bank"
    )
    syn = await synthesize_cumulative_dialogue_intent(
        user_request=msg,
        user_reply="",
        current_entities={},
    )
    ents = syn["entities"]
    print("Synthesized entities:")
    print(f"  total_amount: {ents.get('total_amount')}")
    print(f"  payment_method: {ents.get('payment_method')}")
    print(f"  bank_name: {ents.get('bank_name')}")
    print(f"  line_items count: {len(ents.get('line_items') or [])}")

    # 2. Intent progression check
    prog = build_intent_progression(
        intent="create_compound_journal",
        entities=ents,
        missing_fields=[],
        status="reviewing",
    )
    print("Progression verified facts:")
    for f in prog["verified_facts"]:
        print(f"   {f['label']}: {f['value']}")

    # 3. Post compound split transaction to General Ledger
    d_items = [
        DisaggregatedLineItem(
            description=it.get("description"),
            amount=it.get("amount"),
            category=it.get("category"),
            nature=it.get("nature"),
            ifrs_standard=it.get("ifrs_standard"),
            account_code=it.get("account_code"),
            account_name=it.get("account_name"),
        )
        for it in ents["line_items"]
    ]
    comp_res = MultiItemDisaggregationResult(
        line_items=d_items,
        total_amount=ents.get("total_amount"),
        payment_method="BANK_TRANSFER",
        bank_name="Meezan Bank",
        sum_line_amounts=250000.0,
    )
    journal_dict = comp_res.to_compound_journal(
        transaction_date="2026-11-22",
        narration="Multi-Entity Split: Office Rent, Electricity, Laptop (Phase 4A)",
    )
    print("Posting Compound Journal payload via tool router...")
    user_id = uuid.uuid4()
    auth = AuthContext(
        user_id=user_id,
        organization_id=org_id,
        role_code="owner",
        role_permissions=["ai:full"],
    )
    t_call = ToolCall(tool_name="create_compound_journal", arguments=journal_dict)
    t_res = await route_tool_call(t_call, organization_id=org_id, user_id=user_id, auth=auth)
    assert t_res.success, f"create_compound_journal failed: {t_res.error}"
    post_res = t_res.data
    new_jv_id = post_res.get("journal_entry_id") or post_res.get("id")
    new_jv_num = post_res.get("entry_number") or post_res.get("journal_number")
    print(f"Compound journal posted successfully: {new_jv_num} ({new_jv_id}), status: {post_res.get('status')}")

    # 4. Reversal Voucher (Phase 4B)
    print(f"Now testing One-Click Reversal for {new_jv_num} ({new_jv_id})...")
    rev_call = ToolCall(
        tool_name="reverse_journal",
        arguments={"entry_id": str(new_jv_id), "reason": "One-click conversational reversal test"}
    )
    rev_res_tool = await route_tool_call(rev_call, organization_id=org_id, user_id=user_id, auth=auth)
    assert rev_res_tool.success, f"reverse_journal failed: {rev_res_tool.error}"
    rev_res = rev_res_tool.data
    print("Reversal response:", rev_res)

    # 5. Verify database records
    original_row = await fetch_one("journal_entries", filters={"id": str(new_jv_id)})
    print(f"Original voucher status in DB: {original_row.get('journal_number')} -> {original_row.get('status')}")
    assert original_row.get("status") == "REVERSED", f"Expected REVERSED, got {original_row.get('status')}"

    rev_id = rev_res.get("result") or rev_res.get("reversal_entry_id")
    reversal_row = await fetch_one("journal_entries", filters={"id": str(rev_id)})
    print(
        f"Reversal voucher in DB: {reversal_row.get('journal_number')} -> {reversal_row.get('status')}, "
        f"Reversal of: {reversal_row.get('reversal_of_entry_id')}"
    )
    assert reversal_row.get("reversal_of_entry_id") == str(new_jv_id)

    print("\n==============================================")
    print("🎯 ALL PHASE 4 LIVE AUDIT CHECKS PASSED 100%!")
    print("==============================================")


if __name__ == "__main__":
    asyncio.run(verify_flow())
