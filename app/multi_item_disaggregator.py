"""Multi-Item Conversational Disaggregator (DOC-ACC-2026-V1 Section 6).

Parses composite conversational accounting statements into individual line items
compatible with LineItemArgs, validates arithmetic balance (sum(lines) == total),
classifies economic nature (IAS 1 vs IAS 16 vs IAS 2), and prepares tool payloads
for compound journal entries, cash purchases, or purchase bills.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

import structlog

from app.tools import LineItemArgs, JournalLineArgs

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Account & Category Taxonomy per Authoritative Chart of Accounts (IFRS / ITO)
# ---------------------------------------------------------------------------

_ACCOUNT_TAXONOMY = {
    # Non-Current Assets (IAS 16 Property, Plant & Equipment)
    "computer": {
        "category": "Computer Equipment",
        "nature": "FIXED_ASSET",
        "account_code": "1520",
        "account_name": "Computer & IT Equipment",
        "ifrs_standard": "IAS 16",
        "is_durable": True,
        "default_useful_life": 3,
    },
    "furniture": {
        "category": "Furniture & Fixtures",
        "nature": "FIXED_ASSET",
        "account_code": "1510",
        "account_name": "Furniture & Fixtures",
        "ifrs_standard": "IAS 16",
        "is_durable": True,
        "default_useful_life": 5,
    },
    "machinery": {
        "category": "Plant & Machinery",
        "nature": "FIXED_ASSET",
        "account_code": "1530",
        "account_name": "Plant, Machinery & Generators",
        "ifrs_standard": "IAS 16",
        "is_durable": True,
        "default_useful_life": 10,
    },
    "vehicle": {
        "category": "Motor Vehicles",
        "nature": "FIXED_ASSET",
        "account_code": "1540",
        "account_name": "Motor Vehicles",
        "ifrs_standard": "IAS 16",
        "is_durable": True,
        "default_useful_life": 5,
    },
    # Operating Expenses (IAS 1)
    "rent": {
        "category": "Rent",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6210",
        "account_name": "Rent",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "utilities": {
        "category": "Utilities",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6220",
        "account_name": "Utilities",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "communication": {
        "category": "Communication",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6130",
        "account_name": "Communication",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "supplies": {
        "category": "Office Supplies",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6140",
        "account_name": "Office Supplies & Consumables",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "salaries": {
        "category": "Salaries",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6150",
        "account_name": "Salaries, Wages & Employee Benefits",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "repairs": {
        "category": "Repairs & Maintenance",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6160",
        "account_name": "Repairs & Maintenance",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "cloud": {
        "category": "Cloud Infrastructure",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6210",
        "account_name": "Cloud & Hosting Infrastructure",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "software": {
        "category": "Software Subscriptions",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6220",
        "account_name": "Software Subscriptions & SaaS",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "legal": {
        "category": "Legal & Professional",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6310",
        "account_name": "Legal & Professional Retainers",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "audit": {
        "category": "Audit & Tax Consultancy",
        "nature": "OPERATING_EXPENSE",
        "account_code": "6320",
        "account_name": "Audit & Tax Consultancy Fees",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "marketing": {
        "category": "Marketing & Advertising",
        "nature": "OPERATING_EXPENSE",
        "account_code": "7010",
        "account_name": "Advertising & Digital Marketing",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "shipping": {
        "category": "Shipping & Freight",
        "nature": "OPERATING_EXPENSE",
        "account_code": "7020",
        "account_name": "Outbound Freight, Shipping & Courier Delivery",
        "ifrs_standard": "IAS 1",
        "is_durable": False,
    },
    "inventory": {
        "category": "Inventory",
        "nature": "INVENTORY",
        "account_code": "1200",
        "account_name": "Merchandise Inventory",
        "ifrs_standard": "IAS 2",
        "is_durable": False,
    },
}

# Capitalization threshold per IAS 16 & Section 2.3 of Accounting Specifications
CAPITALIZATION_SINGLE_ITEM_THRESHOLD = 50000.0
CAPITALIZATION_AGGREGATE_BLOCK_THRESHOLD = 100000.0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DisaggregatedLineItem(BaseModel):
    """Structured line item decomposed from conversational prompt."""
    description: str
    amount: float
    quantity: float = 1.0
    unit_price: float = 0.0
    category: str
    nature: str
    is_fixed_asset: bool = False
    is_inventory: bool = False
    account_id: Optional[str] = None
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    ifrs_standard: Optional[str] = None

    def to_line_item_args(self) -> LineItemArgs:
        """Convert to LineItemArgs compatible with tool execution."""
        return LineItemArgs(
            description=self.description,
            quantity=self.quantity,
            unit_price=self.unit_price or self.amount,
            line_total=self.amount,
            is_inventory=self.is_inventory,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        out: Dict[str, Any] = {
            "description": self.description,
            "amount": self.amount,
            "quantity": self.quantity,
            "unit_price": self.unit_price or self.amount,
            "line_total": self.amount,
            "category": self.category,
            "nature": self.nature,
            "is_fixed_asset": self.is_fixed_asset,
            "is_inventory": self.is_inventory,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "ifrs_standard": self.ifrs_standard,
        }
        if self.account_id:
            out["account_id"] = self.account_id
        return out


class MultiItemDisaggregationResult(BaseModel):
    """Result of multi-item conversational disaggregation."""
    is_composite: bool = True
    total_amount: float = 0.0
    currency: str = "PKR"
    payment_method: Optional[str] = None
    bank_name: Optional[str] = None
    counterparty: Optional[str] = None
    line_items: List[DisaggregatedLineItem] = Field(default_factory=list)
    sum_line_amounts: float = 0.0
    is_balanced: bool = True
    balance_discrepancy: float = 0.0
    recommended_action: str = "COMPOUND_JOURNAL"
    validation_error: Optional[str] = None
    fixed_asset_registrations_needed: List[Dict[str, Any]] = Field(default_factory=list)
    statutory_notes: List[str] = Field(default_factory=list)

    def to_line_item_args_list(self) -> List[LineItemArgs]:
        """Convert all line items to LineItemArgs list."""
        return [item.to_line_item_args() for item in self.line_items]

    def to_compound_journal(
        self,
        transaction_date: Optional[str] = None,
        narration: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build compound journal entry dictionary adhering to double-entry balance."""
        credit_account_code = "1010" if self.payment_method == "BANK_TRANSFER" else "1020"
        credit_account_name = f"{self.bank_name or 'Bank'}" if self.payment_method == "BANK_TRANSFER" else "Cash in Hand"

        journal_lines: List[Dict[str, Any]] = []
        for item in self.line_items:
            acc_c = item.account_code
            acc_n = item.account_name or item.category
            d_low = f"{item.description} {item.category}".lower()
            if not item.account_id and (not acc_c or acc_c in ("6000", "6100", "6140", "6200")):
                if "rent" in d_low:
                    acc_c = "6210"
                    acc_n = "Rent"
                elif any(k in d_low for k in ("utilit", "electric", "power", "water", "gas")):
                    acc_c = "6220"
                    acc_n = "Utilities"
                elif "computer" in d_low or "laptop" in d_low or item.nature == "FIXED_ASSET" or "IAS 16" in str(item.ifrs_standard or ""):
                    acc_c = "1500"
                    acc_n = "Computer Equipment"
                else:
                    acc_c = acc_c or "6140"
                    acc_n = acc_n or "Office Supplies & Consumables"
            line_payload: Dict[str, Any] = {
                "account_code": acc_c,
                "account_name": acc_n,
                "debit": item.amount,
                "credit": 0.0,
                "description": item.description,
            }
            if item.account_id:
                line_payload["account_id"] = item.account_id
            journal_lines.append(line_payload)

        # Balancing credit leg
        journal_lines.append({
            "account_code": credit_account_code,
            "account_name": credit_account_name,
            "debit": 0.0,
            "credit": self.total_amount,
            "description": narration or f"Settlement via {self.bank_name or self.payment_method or 'Cash'}",
        })

        return {
            "transaction_date": transaction_date,
            "description": narration or f"Disaggregated payment: {len(self.line_items)} items",
            "lines": journal_lines,
            "total_debit": self.sum_line_amounts,
            "total_credit": self.total_amount,
            "balanced": self.is_balanced,
            "currency_code": self.currency,
        }

    def to_cash_purchase_payload(self) -> Dict[str, Any]:
        """Build payload ready for record_cash_purchase tool."""
        return {
            "amount": self.total_amount,
            "payment_method": self.payment_method or "CASH",
            "bank_name": self.bank_name,
            "items": [item.to_dict() for item in self.line_items],
            "description": f"Purchase of {len(self.line_items)} items: " + ", ".join(i.description for i in self.line_items),
        }

    def to_purchase_bill_payload(self, supplier_id: str) -> Dict[str, Any]:
        """Build payload ready for create_purchase_bill tool."""
        return {
            "supplier_id": supplier_id,
            "subtotal": self.sum_line_amounts,
            "total": self.total_amount,
            "currency_code": self.currency,
            "payment_method": self.payment_method,
            "items": [item.to_dict() for item in self.line_items],
            "notes": f"Disaggregated purchase bill with {len(self.line_items)} line items",
        }


# ---------------------------------------------------------------------------
# Numerical & Text Parsing Helpers
# ---------------------------------------------------------------------------

def _parse_amount(val_str: str) -> Optional[float]:
    """Parse string representations of numbers like '250,000', '70k', '1.5M'."""
    if not val_str:
        return None
    s = val_str.strip().replace(",", "").lower()
    s = re.sub(r"^(?:pkr|rs\.?|\$)\s*", "", s)
    try:
        if s.endswith("k"):
            return float(s[:-1]) * 1000.0
        elif s.endswith("m"):
            return float(s[:-1]) * 1000000.0
        elif s.endswith("b"):
            return float(s[:-1]) * 1000000000.0
        return float(s)
    except (ValueError, TypeError):
        return None


def _extract_payment_channel(text: str) -> Tuple[Optional[str], Optional[str], str]:
    """Extract payment channel (method, bank_name) and stripped text across entire sentence."""
    method: Optional[str] = None
    bank_name: Optional[str] = None
    clean = text

    # Check bank pattern: e.g. "via Meezan Bank", "through HBL", "via Meezan Bank transfer"
    m_bank = re.search(r'\b(?:via|through|using)\s+([A-Za-z0-9\s]+?(?:Bank|bank))\b', clean, re.I)
    if m_bank:
        method = "BANK_TRANSFER"
        bank_name = m_bank.group(1).strip()
        clean = re.sub(r'\b(?:via|through|using)\s+' + re.escape(m_bank.group(1)) + r'(?:\s+transfer)?\b', '', clean, flags=re.I)
    elif re.search(r'\b(?:via\s+bank\s+transfer|by\s+bank\s+transfer|bank\s+transfer|online\s+transfer)\b', clean, re.I):
        method = "BANK_TRANSFER"
        clean = re.sub(r'\b(?:via|by|through|using)?\s*(?:bank\s+transfer|online\s+transfer)\b', '', clean, flags=re.I)

    # Check cash pattern: e.g. "in cash", "via cash", "paid in cash", "by cash"
    if re.search(r'\b(?:in\s+cash|via\s+cash|paid\s+in\s+cash|by\s+cash|cash\s+payment)\b', clean, re.I):
        method = "CASH"
        clean = re.sub(r'\b(?:in\s+cash|via\s+cash|paid\s+in\s+cash|by\s+cash|cash\s+payment)\b', '', clean, flags=re.I)
    elif re.search(r'\b(?:via|by|through)\s+cash\b', clean, re.I):
        method = "CASH"
        clean = re.sub(r'\b(?:via|by|through)\s+cash\b', '', clean, flags=re.I)

    # Check cheque pattern: e.g. "via cheque", "by crossed cheque"
    if re.search(r'\b(?:via|by|through)?\s*(?:crossed\s+cheque|cheque|check)\b', clean, re.I):
        method = "CHEQUE"
        clean = re.sub(r'\b(?:via|by|through)?\s*(?:crossed\s+cheque|cheque|check)\b', '', clean, flags=re.I)

    # Check card pattern
    if re.search(r'\b(?:via|by|through)?\s*(?:credit\s+card|debit\s+card|card)\b', clean, re.I):
        method = "CARD"
        clean = re.sub(r'\b(?:via|by|through)?\s*(?:credit\s+card|debit\s+card|card)\b', '', clean, flags=re.I)

    clean = re.sub(r'\s+', ' ', clean).strip()
    return method, bank_name, clean


def _classify_nature_and_category(
    description: str,
    amount: float,
    quantity: float = 1.0,
    org_type: str = "SERVICE",
) -> Tuple[str, str, bool, bool, str, str, str]:
    """Determine category, nature, is_fixed_asset, is_inventory, account_code, account_name, and ifrs_standard.

    Follows DOC-ACC-2026-V1 Section 2 & Section 6.
    """
    desc_lower = description.lower()

    # 1. Computer Equipment
    if any(k in desc_lower for k in ("laptop", "computer", "macbook", "pc", "server", "workstation", "monitor", "display")):
        total_cost = amount
        # Capitalization check: >= 50,000 or bulk >= 100,000
        if total_cost >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD or (quantity > 1 and total_cost >= CAPITALIZATION_AGGREGATE_BLOCK_THRESHOLD):
            t = _ACCOUNT_TAXONOMY["computer"]
            return t["category"], t["nature"], True, False, t["account_code"], t["account_name"], t["ifrs_standard"]
        else:
            t = _ACCOUNT_TAXONOMY["supplies"]
            return "Computer Supplies", "OPERATING_EXPENSE", False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 2. Furniture & Fixtures
    if any(k in desc_lower for k in ("desk", "chair", "table", "sofa", "furniture", "fixture", "cabinet", "shelf", "workstation table")):
        total_cost = amount
        if total_cost >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD or (quantity > 1 and total_cost >= CAPITALIZATION_AGGREGATE_BLOCK_THRESHOLD):
            t = _ACCOUNT_TAXONOMY["furniture"]
            return t["category"], t["nature"], True, False, t["account_code"], t["account_name"], t["ifrs_standard"]
        else:
            t = _ACCOUNT_TAXONOMY["supplies"]
            return "Office Supplies", "OPERATING_EXPENSE", False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 3. Machinery & Equipment
    if any(k in desc_lower for k in ("machinery", "machine", "generator", "air conditioner", "ac unit", "plant", "ups inverter")):
        total_cost = amount
        if total_cost >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD:
            t = _ACCOUNT_TAXONOMY["machinery"]
            return t["category"], t["nature"], True, False, t["account_code"], t["account_name"], t["ifrs_standard"]
        else:
            t = _ACCOUNT_TAXONOMY["repairs"]
            return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 4. Vehicles
    if any(k in desc_lower for k in ("car", "vehicle", "van", "truck", "motorcycle", "bike")):
        t = _ACCOUNT_TAXONOMY["vehicle"]
        return t["category"], t["nature"], True, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 5. Rent
    if any(k in desc_lower for k in ("rent", "office rent", "building rent", "warehouse rent", "shop rent")):
        t = _ACCOUNT_TAXONOMY["rent"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 6. Utilities
    if any(k in desc_lower for k in ("electricity", "electric bill", "power bill", "lesco", "kelectric", "gas bill", "water bill", "utilities")):
        t = _ACCOUNT_TAXONOMY["utilities"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 7. Communication
    if any(k in desc_lower for k in ("internet", "broadband", "telephone", "phone", "mobile bill", "courier", "communication")):
        t = _ACCOUNT_TAXONOMY["communication"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 8. Cloud & Hosting
    if any(k in desc_lower for k in ("aws", "cloud", "hosting", "azure", "gcp", "digitalocean", "server hosting")):
        t = _ACCOUNT_TAXONOMY["cloud"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 9. Software Subscriptions
    if any(k in desc_lower for k in ("software", "saas", "subscription", "github", "figma", "slack", "zoom", "adobe", "google workspace")):
        t = _ACCOUNT_TAXONOMY["software"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 10. Legal & Professional
    if any(k in desc_lower for k in ("legal", "lawyer", "advocate", "retainer", "attorney")):
        t = _ACCOUNT_TAXONOMY["legal"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 11. Audit & Tax
    if any(k in desc_lower for k in ("audit", "tax consultant", "tax consultancy", "accounting fee")):
        t = _ACCOUNT_TAXONOMY["audit"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 12. Salaries & Payroll
    if any(k in desc_lower for k in ("salary", "salaries", "wages", "payroll", "stipend")):
        t = _ACCOUNT_TAXONOMY["salaries"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 13. Marketing & Advertising
    if any(k in desc_lower for k in ("marketing", "advertising", "ad campaign", "google ads", "meta ads", "facebook ads")):
        t = _ACCOUNT_TAXONOMY["marketing"]
        return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 14. Trading Inventory
    if any(k in desc_lower for k in ("resale stock", "trading goods", "merchandise inventory", "raw materials")):
        t = _ACCOUNT_TAXONOMY["inventory"]
        return t["category"], t["nature"], False, True, t["account_code"], t["account_name"], t["ifrs_standard"]

    # 15. Default Consumables / Supplies
    t = _ACCOUNT_TAXONOMY["supplies"]
    return t["category"], t["nature"], False, False, t["account_code"], t["account_name"], t["ifrs_standard"]


def extract_line_item_amount(item: Dict[str, Any]) -> float:
    """Resolve line item monetary total across schema variants (amount / line_total / unit_price*qty)."""
    for key in ("amount", "line_total", "total_amount"):
        val = item.get(key)
        if val is not None:
            try:
                num = float(str(val).replace(",", "").strip())
                if num > 0:
                    return num
            except (ValueError, TypeError):
                continue
    try:
        qty = float(item.get("quantity") or 1.0)
        up = float(str(item.get("unit_price") or 0.0).replace(",", "").strip())
        if up > 0:
            return round(qty * up, 2)
    except (ValueError, TypeError):
        pass
    return 0.0


def build_compound_journal_from_entities(entities: Dict[str, Any]) -> Dict[str, Any]:
    """Build compound journal arguments from entity dict containing disaggregated line_items."""
    from app.date_parser import coerce_iso_date

    raw_items = entities.get("line_items") or []
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except Exception:
            raw_items = []
    if not isinstance(raw_items, list):
        raw_items = []
    d_items: List[DisaggregatedLineItem] = []
    for ri in raw_items:
        if isinstance(ri, dict):
            desc = str(ri.get("description") or ri.get("name") or "Line Item").strip()
            amt = extract_line_item_amount(ri)
            qty = float(ri.get("quantity") or 1.0)
            cat, nat, is_fa, _, def_code, def_name, def_ifrs = _classify_nature_and_category(
                description=desc,
                amount=amt,
                quantity=qty,
            )
            d_items.append(DisaggregatedLineItem(
                description=desc,
                amount=amt,
                quantity=qty,
                unit_price=float(ri.get("unit_price") or (amt / qty if qty > 0 else amt)),
                category=str(ri.get("category") or cat),
                nature=str(ri.get("nature") or nat),
                is_fixed_asset=bool(ri.get("is_fixed_asset", is_fa)),
                ifrs_standard=str(ri.get("ifrs_standard") or def_ifrs),
                account_id=str(ri["account_id"]) if ri.get("account_id") else None,
                account_code=ri.get("account_code") or def_code,
                account_name=ri.get("account_name") or def_name,
            ))

    pm_comp = str(entities.get("payment_method") or entities.get("payment_channel") or "BANK").upper()
    sum_lines = round(sum(it.amount for it in d_items), 2)
    try:
        total_amt = float(str(entities.get("amount") or sum_lines).replace(",", "").strip())
    except (ValueError, TypeError):
        total_amt = sum_lines
    if total_amt <= 0 or abs(total_amt - sum_lines) > 0.01:
        total_amt = sum_lines if sum_lines > 0 else total_amt

    comp_res = MultiItemDisaggregationResult(
        line_items=d_items,
        total_amount=total_amt,
        payment_method="BANK_TRANSFER" if ("BANK" in pm_comp or "TRANSFER" in pm_comp) else "CASH",
        bank_name=entities.get("bank_name"),
        sum_line_amounts=sum_lines,
        is_balanced=abs(total_amt - sum_lines) < 0.01,
    )
    iso_dt = coerce_iso_date(entities.get("transaction_date") or entities.get("date"))
    return comp_res.to_compound_journal(
        transaction_date=iso_dt,
        narration=f"Disaggregated compound transaction: {len(d_items)} line items",
    )


async def resolve_compound_lines_to_org_coa(
    organization_id: Any,
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Resolve line_items / journal lines onto the organization's live active COA accounts."""
    if not items or not isinstance(items, list):
        return items
    try:
        import uuid as _uuid
        from app.accounting_engine import _grouping_account_ids, _resolve_compound_line_account

        org_uuid = organization_id if isinstance(organization_id, _uuid.UUID) else _uuid.UUID(str(organization_id))
        group_ids = await _grouping_account_ids(org_uuid)
        enriched: List[Dict[str, Any]] = []
        for row in items:
            if not isinstance(row, dict):
                enriched.append(row)
                continue
            copy_row = dict(row)
            acc = await _resolve_compound_line_account(
                org_uuid,
                raw_acc_id=copy_row.get("account_id"),
                code=str(copy_row.get("account_code") or "").strip(),
                name=str(copy_row.get("account_name") or copy_row.get("category") or "").strip(),
                line_desc=str(copy_row.get("description") or "").strip(),
                group_ids=group_ids,
            )
            if acc and acc.get("id") and acc.get("id") not in group_ids and acc.get("is_active") is not False:
                copy_row["account_id"] = str(acc["id"])
                if acc.get("code"):
                    copy_row["account_code"] = str(acc["code"])
                if acc.get("name"):
                    copy_row["account_name"] = str(acc["name"])
            enriched.append(copy_row)
        return enriched
    except Exception as exc:
        log.debug("multi_item_disaggregator.coa_enrich_skipped", error=str(exc)[:120])
        return items


def _format_description(raw_desc: str) -> str:
    """Normalize description string to clean sentence case."""
    clean = raw_desc.strip()
    if not clean:
        return "Miscellaneous Expense"
    # Capitalize first character, keep remaining case
    return clean[0].upper() + clean[1:]


def _parse_single_segment(segment: str) -> Optional[Tuple[str, float, float]]:
    """Parse an item segment string into (description, amount, quantity)."""
    seg = segment.strip()
    if not seg:
        return None

    # Strip conversational prefixes (including leading subject + verb like "Digital Creators purchased")
    seg = re.sub(r'^(?:[A-Za-z0-9\s]+\s+)?(?:bought|purchased|paid|spent|got|acquired)\s+(?:an?\s+)?', '', seg, flags=re.I)
    seg = re.sub(r'^(?:and\s+)?(?:an?\s+)', '', seg, flags=re.I).strip()

    # Strip trailing counterparty like "from Apex Supplies" or "to Vendor"
    m_from = re.search(r'\s+(?:from|to|with)\s+([A-Za-z0-9\s&\'\.\-]+)$', seg, re.I)
    if m_from:
        seg = seg[:m_from.start()].strip()

    # Pattern 1 (Priority): <description> for/costing/worth <amount>
    # e.g. "5 workstation tables for 120,000", "office rent for 150,000", "bought an executive laptop for 70,000"
    m_1 = re.match(
        r'^(.+?)\s+(?:for|costing|worth|amounting to|at)\s+(?:PKR|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?|\d+[kKmMbB])$',
        seg,
        re.I,
    )
    if m_1:
        desc = m_1.group(1).strip()
        amt = _parse_amount(m_1.group(2))
        if amt is not None and desc:
            m_qty = re.match(r'^(\d+)\s+(.+)$', desc)
            if m_qty:
                qty = float(m_qty.group(1))
                return m_qty.group(2).strip(), amt, qty
            return desc, amt, 1.0

    # Pattern 2: <amount> for <description> or <amount> <description>
    # e.g. "150,000 for office rent" or "30,000 electricity bill" or "70k laptop"
    m_2 = re.match(
        r'^(?:PKR|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?|\d+[kKmMbB])\s+(?:for\s+)?(.+)$',
        seg,
        re.I,
    )
    if m_2:
        amt = _parse_amount(m_2.group(1))
        desc = m_2.group(2).strip()
        if amt is not None and desc:
            m_qty = re.match(r'^(\d+)\s+(.+)$', desc)
            if m_qty:
                qty = float(m_qty.group(1))
                return m_qty.group(2).strip(), amt, qty
            return desc, amt, 1.0

    # Pattern 3: <description> <amount> at end without 'for'
    # e.g. "executive laptop 70,000"
    m_3 = re.match(
        r'^(.+?)\s+(?:PKR|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?|\d+[kKmMbB])$',
        seg,
        re.I,
    )
    if m_3:
        desc = m_3.group(1).strip()
        amt = _parse_amount(m_3.group(2))
        if amt is not None and desc:
            m_qty = re.match(r'^(\d+)\s+(.+)$', desc)
            if m_qty:
                qty = float(m_qty.group(1))
                return m_qty.group(2).strip(), amt, qty
            return desc, amt, 1.0

    return None


# ---------------------------------------------------------------------------
# Main Disaggregation Engine
# ---------------------------------------------------------------------------

def _disaggregate_deterministic(
    user_message: str,
    entities: Optional[Dict[str, Any]] = None,
    default_currency: str = "PKR",
) -> MultiItemDisaggregationResult:
    """Deterministic, robust fallback disaggregation adhering to strict accounting rules."""
    entities = entities or {}
    msg = str(user_message or "").strip()

    # Step 1: Extract payment channel and bank name from message or entities
    payment_method, bank_name, clean_msg = _extract_payment_channel(msg)
    if not payment_method and entities.get("payment_method"):
        payment_method = str(entities["payment_method"]).upper()
    if not bank_name and entities.get("bank_name"):
        bank_name = str(entities["bank_name"])

    # Step 2: Extract explicit total stated upfront
    stated_total: Optional[float] = None
    body_text = clean_msg

    # Check for prefix like "Paid 250,000 today: ...", "Spent 100,000: ..."
    m_prefix = re.match(
        r'^(?:paid|spent|purchased|disbursed|settled|total)\s+(?:PKR|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?|\d+[kKmMbB])(?:\s+today|\s+yesterday)?\s*:\s*(.*)$',
        clean_msg,
        re.I | re.DOTALL,
    )
    if m_prefix:
        stated_total = _parse_amount(m_prefix.group(1))
        body_text = m_prefix.group(2).strip()
    elif ":" in clean_msg:
        # Check if text before colon contains an amount
        prefix_part, colon_body = clean_msg.split(":", 1)
        m_amt = re.search(r'(?:PKR|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?|\d+[kKmMbB])', prefix_part, re.I)
        if m_amt:
            stated_total = _parse_amount(m_amt.group(1))
            body_text = colon_body.strip()

    # Step 3: Split body into candidate item segments
    # Use negative lookbehind/lookahead to prevent splitting on numbers with commas (e.g. 150,000)
    raw_segments = [
        s.strip()
        for s in re.split(r'(?<!\d)[,;](?!\d)|\band\b', body_text, flags=re.I)
        if s.strip()
    ]

    line_items: List[DisaggregatedLineItem] = []
    fixed_asset_registrations: List[Dict[str, Any]] = []

    for seg in raw_segments:
        # Ignore empty or pure conjunctions
        if not seg or seg.lower() in ("and", "then", "also", "with"):
            continue

        parsed = _parse_single_segment(seg)
        if not parsed:
            continue

        desc, amount, qty = parsed
        formatted_desc = _format_description(desc)
        unit_price = round(amount / qty, 2) if qty > 0 else amount

        category, nature, is_fa, is_inv, acc_code, acc_name, ifrs_std = _classify_nature_and_category(
            description=formatted_desc,
            amount=amount,
            quantity=qty,
        )

        item = DisaggregatedLineItem(
            description=formatted_desc,
            amount=amount,
            quantity=qty,
            unit_price=unit_price,
            category=category,
            nature=nature,
            is_fixed_asset=is_fa,
            is_inventory=is_inv,
            account_code=acc_code,
            account_name=acc_name,
            ifrs_standard=ifrs_std,
        )
        line_items.append(item)

        if is_fa and amount >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD:
            fixed_asset_registrations.append({
                "asset_name": formatted_desc,
                "cost": amount,
                "asset_class": category,
                "account_code": acc_code,
                "useful_life_years": 3 if "Computer" in category else 5,
                "salvage_value": round(amount * 0.05, 2),
            })

    # Fallback: If no segments were parsed, check if the clean_msg itself is a single item
    if not line_items:
        parsed_single = _parse_single_segment(clean_msg)
        if parsed_single:
            desc, amount, qty = parsed_single
            formatted_desc = _format_description(desc)
            unit_price = round(amount / qty, 2) if qty > 0 else amount
            category, nature, is_fa, is_inv, acc_code, acc_name, ifrs_std = _classify_nature_and_category(
                description=formatted_desc,
                amount=amount,
                quantity=qty,
            )
            item = DisaggregatedLineItem(
                description=formatted_desc,
                amount=amount,
                quantity=qty,
                unit_price=unit_price,
                category=category,
                nature=nature,
                is_fixed_asset=is_fa,
                is_inventory=is_inv,
                account_code=acc_code,
                account_name=acc_name,
                ifrs_standard=ifrs_std,
            )
            line_items.append(item)
            if is_fa and amount >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD:
                fixed_asset_registrations.append({
                    "asset_name": formatted_desc,
                    "cost": amount,
                    "asset_class": category,
                    "account_code": acc_code,
                    "useful_life_years": 3 if "Computer" in category else 5,
                    "salvage_value": round(amount * 0.05, 2),
                })

    sum_line_amounts = round(sum(i.amount for i in line_items), 2)

    # Determine total amount & verify arithmetic balance
    if stated_total is not None:
        total_amount = round(stated_total, 2)
    elif entities.get("amount"):
        total_amount = round(float(entities["amount"]), 2)
    else:
        total_amount = sum_line_amounts

    discrepancy = round(abs(total_amount - sum_line_amounts), 2)
    is_balanced = discrepancy < 0.01

    validation_error = None
    if not is_balanced:
        validation_error = (
            f"Sum of line items ({default_currency} {sum_line_amounts:,.2f}) does not match "
            f"total amount ({default_currency} {total_amount:,.2f}). "
            f"Discrepancy: {default_currency} {discrepancy:,.2f}."
        )

    # Determine recommended action
    has_fixed_assets = any(i.is_fixed_asset for i in line_items)
    is_composite = len(line_items) > 1

    if is_composite or has_fixed_assets:
        recommended_action = "COMPOUND_JOURNAL"
    elif payment_method == "CASH":
        recommended_action = "RECORD_CASH_PURCHASE"
    else:
        recommended_action = "CREATE_PURCHASE_BILL"

    statutory_notes = []
    if payment_method == "CASH" and total_amount > 50000.0:
        statutory_notes.append(
            f"SECTION 73 HAZARD: Total cash outflow of PKR {total_amount:,.2f} exceeds "
            "the PKR 50,000 threshold under Section 73 & Section 21(l) of ITO 2001."
        )

    return MultiItemDisaggregationResult(
        is_composite=is_composite,
        total_amount=total_amount,
        currency=default_currency,
        payment_method=payment_method,
        bank_name=bank_name,
        line_items=line_items,
        sum_line_amounts=sum_line_amounts,
        is_balanced=is_balanced,
        balance_discrepancy=discrepancy,
        recommended_action=recommended_action,
        validation_error=validation_error,
        fixed_asset_registrations_needed=fixed_asset_registrations,
        statutory_notes=statutory_notes,
    )


async def disaggregate_conversational_items(
    user_message: str,
    entities: Optional[Dict[str, Any]] = None,
    default_currency: str = "PKR",
    client: Optional[Any] = None,
    timeout: Optional[float] = None,
) -> MultiItemDisaggregationResult:
    """Disaggregate composite conversational user messages into distinct line items via LLM-first reasoning.

    Applies cognitive natural language understanding to extract items, quantities, and amounts,
    enforcing double-entry arithmetic balance and IAS 16 / IAS 2 / IAS 1 classification.
    """
    from app.config import get_settings

    settings = get_settings()
    llm_enabled = getattr(settings, "multi_item_disaggregator_enabled", True)

    if not llm_enabled:
        return _disaggregate_deterministic(user_message, entities, default_currency)

    try:
        if client is None:
            from app.ai_orchestrator import get_client
            client = get_client()

        prompt = (
            "YOU ARE THE SENIOR CHARTERED ACCOUNTANT (FCA) & FINANCIAL CONTROLLER.\n"
            "Decompose this conversational transaction message into discrete line items with rigorous accounting classification.\n\n"
            f"TRANSACTION MESSAGE: {user_message}\n"
            f"KNOWN EXTRACTED ENTITIES: {json.dumps(entities or {}, default=str)}\n\n"
            "MANDATORY ACCOUNTING SPECIFICATIONS:\n"
            "1. Identify all discrete goods or services purchased/sold.\n"
            "2. For each line item:\n"
            "   - description: clean, professional description (e.g. 'Office Chair', 'Dell 4K Editing Monitor')\n"
            "   - quantity: numerical quantity (default 1.0)\n"
            "   - amount: total line amount in PKR\n"
            "   - unit_price: unit price (amount / quantity)\n"
            "   - nature: FIXED_ASSET | INVENTORY | OPERATING_EXPENSE | CONSUMABLE | SERVICE\n"
            "   - is_fixed_asset: true if durable asset meeting IAS 16 criteria (>= PKR 50,000 single or >= PKR 100,000 bulk)\n"
            "   - is_inventory: true if held for resale under IAS 2\n"
            "   - category: Accounting Category (e.g. 'Furniture & Fixtures', 'Computer Equipment', 'Office Supplies')\n"
            "   - account_code: standard 4-digit code (e.g. 1510, 1520, 6140, 1200)\n"
            "   - account_name: standard account title\n"
            "   - ifrs_standard: IAS 16 | IAS 2 | IAS 1 | IFRS 15\n"
            "3. Identify payment method: CASH | BANK_TRANSFER | CREDIT | UNKNOWN\n"
            "4. Identify bank name if specified (e.g. Meezan Bank, HBL)\n"
            "5. Calculate total amount (sum of all items or stated total).\n\n"
            "Reply with STRICT JSON ONLY matching:\n"
            "{\n"
            '  "is_composite": true,\n'
            '  "total_amount": 155000.0,\n'
            '  "payment_method": "CASH",\n'
            '  "bank_name": null,\n'
            '  "counterparty": "Apex Supplies",\n'
            '  "line_items": [\n'
            '    {\n'
            '      "description": "executive office chairs",\n'
            '      "quantity": 2.0,\n'
            '      "amount": 70000.0,\n'
            '      "unit_price": 35000.0,\n'
            '      "nature": "FIXED_ASSET",\n'
            '      "is_fixed_asset": true,\n'
            '      "is_inventory": false,\n'
            '      "category": "Furniture & Fixtures",\n'
            '      "account_code": "1510",\n'
            '      "account_name": "Furniture & Fixtures",\n'
            '      "ifrs_standard": "IAS 16"\n'
            '    }\n'
            '  ],\n'
            '  "reasoning": "Accounting rationale"\n'
            "}"
        )

        call_timeout = timeout or getattr(settings, "multi_item_disaggregator_timeout", 8.0)
        raw_reply = await asyncio.wait_for(
            client.generate_text_light(prompt=prompt),
            timeout=call_timeout,
        )

        match = re.search(r"\{.*\}", str(raw_reply or ""), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            raw_items = parsed.get("line_items") or []
            if raw_items and isinstance(raw_items, list):
                line_items: List[DisaggregatedLineItem] = []
                fixed_asset_registrations: List[Dict[str, Any]] = []

                for raw_i in raw_items:
                    desc = str(raw_i.get("description") or "Item").strip()
                    amt = float(raw_i.get("amount") or 0.0)
                    qty = float(raw_i.get("quantity") or 1.0)
                    unit_p = float(raw_i.get("unit_price") or (amt / qty if qty > 0 else amt))
                    nature = str(raw_i.get("nature") or "OPERATING_EXPENSE").upper()
                    is_fa = bool(raw_i.get("is_fixed_asset") or nature == "FIXED_ASSET")
                    is_inv = bool(raw_i.get("is_inventory") or nature == "INVENTORY")
                    cat = str(raw_i.get("category") or ("Computer Equipment" if "computer" in desc.lower() else "Office Supplies"))
                    acc_code = str(raw_i.get("account_code") or ("1520" if is_fa else "6140"))
                    acc_name = str(raw_i.get("account_name") or cat)
                    if acc_code in ("6000", "6100", "6200"):
                        d_low = f"{desc} {cat}".lower()
                        if "rent" in d_low:
                            acc_code = "6210"
                            acc_name = "Rent"
                        elif any(k in d_low for k in ("utilit", "electric", "power", "water", "gas")):
                            acc_code = "6220"
                            acc_name = "Utilities"
                        elif "computer" in d_low or "laptop" in d_low:
                            acc_code = "1520"
                            acc_name = "Computer Equipment"
                        else:
                            acc_code = "6140"
                            acc_name = "Office Supplies & Consumables"
                    ifrs_std = str(raw_i.get("ifrs_standard") or ("IAS 16" if is_fa else "IAS 1"))

                    item = DisaggregatedLineItem(
                        description=desc,
                        amount=amt,
                        quantity=qty,
                        unit_price=unit_p,
                        category=cat,
                        nature=nature,
                        is_fixed_asset=is_fa,
                        is_inventory=is_inv,
                        account_code=acc_code,
                        account_name=acc_name,
                        ifrs_standard=ifrs_std,
                    )
                    line_items.append(item)

                    if is_fa and amt >= CAPITALIZATION_SINGLE_ITEM_THRESHOLD:
                        fixed_asset_registrations.append({
                            "asset_name": desc,
                            "cost": amt,
                            "asset_class": cat,
                            "account_code": acc_code,
                            "useful_life_years": 3 if "Computer" in cat else 5,
                            "salvage_value": round(amt * 0.05, 2),
                        })

                sum_line_amounts = round(sum(i.amount for i in line_items), 2)
                raw_total = parsed.get("total_amount")
                total_amount = float(raw_total) if raw_total is not None and float(raw_total) > 0 else sum_line_amounts
                discrepancy = round(abs(total_amount - sum_line_amounts), 2)
                is_balanced = discrepancy < 0.01

                payment_method = str(parsed.get("payment_method") or "").upper()
                if not payment_method or payment_method == "UNKNOWN":
                    pm_det, _, _ = _extract_payment_channel(user_message)
                    payment_method = pm_det or "CASH"

                bank_name = parsed.get("bank_name")
                is_composite = bool(parsed.get("is_composite")) if "is_composite" in parsed else len(line_items) > 1

                recommended_action = "COMPOUND_JOURNAL" if (is_composite or any(i.is_fixed_asset for i in line_items)) else "RECORD_CASH_PURCHASE"

                statutory_notes = []
                if payment_method == "CASH" and total_amount > 50000.0:
                    statutory_notes.append(
                        f"SECTION 73 HAZARD: Total cash outflow of PKR {total_amount:,.2f} exceeds "
                        "the PKR 50,000 threshold under Section 73 & Section 21(l) of ITO 2001."
                    )

                return MultiItemDisaggregationResult(
                    is_composite=is_composite,
                    total_amount=total_amount,
                    currency=default_currency,
                    payment_method=payment_method,
                    bank_name=bank_name,
                    line_items=line_items,
                    sum_line_amounts=sum_line_amounts,
                    is_balanced=is_balanced,
                    balance_discrepancy=discrepancy,
                    recommended_action=recommended_action,
                    validation_error=None if is_balanced else f"Sum of line items does not match total amount.",
                    fixed_asset_registrations_needed=fixed_asset_registrations,
                    statutory_notes=statutory_notes,
                )
    except Exception as exc:
        log.warning("multi_item_disaggregator.llm_fallback", error=str(exc)[:160])

    return _disaggregate_deterministic(user_message, entities, default_currency)
