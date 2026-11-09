import pytest
import asyncio
from app.llm_extraction import enrich_preliminary
from app.accounting_reasoning import preliminary_extraction
from app.analytics_agent import _pattern_gate

def test_pattern_gate_queries():
    # Informational / report questions route to analytics
    assert _pattern_gate("Show me all outstanding supplier bills and upcoming due dates.") is True
    assert _pattern_gate("What is our current cash and bank balance across all accounts?") is True
    assert _pattern_gate("Show this month's revenue, expenses, and net profit.") is True
    assert _pattern_gate("List all unpaid invoices") is True

    # Operational mutations do NOT route to analytics
    assert _pattern_gate("Record cash purchase of Rs 40,000") is False
    assert _pattern_gate("Create customer ABC Ltd") is False
    assert _pattern_gate("Create bank account HBL Main") is False

def test_preliminary_extraction_no_supplier_named_bills():
    prelim = preliminary_extraction("Show me all outstanding supplier bills and upcoming due dates.")
    literals = prelim.get("literals") or {}
    assert literals.get("supplier_name") != "bills"
    assert literals.get("customer_name") != "bills"
    assert "bills" not in (prelim.get("supplier_name") or "")

