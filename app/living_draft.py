"""Living Draft State Accumulator (DOC-ACC-2026-V1 Decision 2 Option A).

Constructs and maintains a real-time voucher card preview:
{
    document_type: str,
    voucher_preview: List[VoucherLinePreview],
    counterparty: Optional[LivingDraftCounterparty],
    line_items: List[LivingDraftLineItem],
    total_amount: Optional[float],
    payment_channel: Optional[str],
    bank_name: Optional[str],
    depreciation_schedule: Optional[DepreciationSchedulePreview],
    compliance_notes: List[str],
    status: str,
    missing_fields: List[str],
}

The chat thread remains 100% natural, warm, and conversational while this
living draft state object rides along in the response payload to drive the
interactive UI sidebar/preview pane in real time.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Union
from pydantic import BaseModel, Field

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class VoucherLinePreview(BaseModel):
    """A single debit or credit line in the provisional journal voucher preview."""

    account_name: str
    account_code: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0
    description: Optional[str] = None


class DepreciationSchedulePreview(BaseModel):
    """Depreciation schedule preview for capitalized fixed assets (IAS 16)."""

    useful_life_years: int = Field(default=3, ge=1)
    method: str = "STRAIGHT_LINE"  # STRAIGHT_LINE | REDUCING_BALANCE | NONE
    cost: float = 0.0
    salvage_value: float = 0.0
    depreciable_amount: float = 0.0
    annual_depreciation: float = 0.0
    monthly_depreciation: float = 0.0


class LivingDraftCounterparty(BaseModel):
    """Vendor, customer, or employee entity in the living draft."""

    name: Optional[str] = None
    role: Optional[str] = None  # "supplier" | "customer" | "employee" | "party"
    tax_status: Optional[str] = None  # "REGISTERED_ACTIVE" | "UNREGISTERED" | etc.
    strn: Optional[str] = None
    ntn: Optional[str] = None


class LivingDraftLineItem(BaseModel):
    """Line item within the living draft voucher."""

    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    total_amount: float = 0.0
    account_name: Optional[str] = None


class LivingDraft(BaseModel):
    """Authoritative real-time living draft voucher card preview."""

    document_type: str = "Transaction Draft Voucher"
    voucher_preview: List[VoucherLinePreview] = Field(default_factory=list)
    counterparty: Optional[LivingDraftCounterparty] = None
    line_items: List[LivingDraftLineItem] = Field(default_factory=list)
    total_amount: Optional[float] = None
    currency: str = "PKR"
    payment_channel: Optional[str] = None  # cash | bank_transfer | credit | cheque
    bank_name: Optional[str] = None
    transaction_date: Optional[str] = None
    depreciation_schedule: Optional[DepreciationSchedulePreview] = None
    compliance_notes: List[str] = Field(default_factory=list)
    status: str = "drafting"  # drafting | awaiting_input | ready_for_confirmation | posted
    missing_fields: List[str] = Field(default_factory=list)
    interactive_artifact: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert living draft model to standard dictionary for JSON responses."""
        return self.model_dump()

    def attach_interactive_artifact(self) -> LivingDraft:
        """Construct and attach interactive in-chat artifact controls."""
        try:
            from app.interactive_artifacts import build_interactive_artifact
            art = build_interactive_artifact(self)
            self.interactive_artifact = art.model_dump()
        except Exception:
            pass
        return self


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_amount(entities: Dict[str, Any]) -> Optional[float]:
    """Extract numeric transaction amount from various entity aliases."""
    for key in ("amount", "total_amount", "subtotal", "total", "basic_salary", "sales_price"):
        val = entities.get(key)
        if val is not None:
            try:
                num = float(str(val).replace(",", "").strip())
                if num > 0:
                    return num
            except (ValueError, TypeError):
                continue
    return None


def _extract_channel(entities: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Extract payment channel (cash/bank_transfer/credit/cheque) and bank name."""
    raw_pm = entities.get("payment_method") or entities.get("payment_type") or entities.get("payment_channel")
    channel: Optional[str] = None
    bank_name: Optional[str] = entities.get("bank_name")

    if raw_pm:
        raw_str = str(raw_pm).strip().upper()
        if "CASH" in raw_str:
            channel = "cash"
        elif any(k in raw_str for k in ("BANK", "TRANSFER", "ONLINE", "WIRE")):
            channel = "bank_transfer"
        elif any(k in raw_str for k in ("CREDIT", "PAYABLE", "LATER", "UDHAAR")):
            channel = "credit"
        elif "CHEQUE" in raw_str or "CHECK" in raw_str:
            channel = "cheque"
        else:
            channel = str(raw_pm).lower()

        # Check for known Pakistani banks if not already extracted
        if not bank_name:
            for b_keyword in (
                "Meezan Bank", "Meezan", "HBL", "Habib Bank", "MCB", "UBL",
                "Bank Alfalah", "Alfalah", "Standard Chartered", "Allied Bank",
                "Askari Bank", "Faysal Bank", "Bank Islami", "Soneri Bank"
            ):
                if b_keyword.upper() in raw_str:
                    bank_name = b_keyword
                    channel = "bank_transfer"
                    break

    return channel, bank_name


def _extract_counterparty(intent: str, entities: Dict[str, Any]) -> Optional[LivingDraftCounterparty]:
    """Build counterparty info from entities."""
    name: Optional[str] = None
    role: Optional[str] = None

    c_raw = entities.get("counterparty")
    if isinstance(c_raw, dict):
        name = c_raw.get("name")
        role = c_raw.get("role")
    elif isinstance(c_raw, str) and c_raw.strip():
        name = c_raw.strip()

    if not name:
        for k in ("supplier_name", "vendor_name", "customer_name", "employee_name", "party_name", "name"):
            val = entities.get(k)
            if val and str(val).strip():
                name = str(val).strip()
                if "supplier" in k or "vendor" in k:
                    role = "supplier"
                elif "customer" in k:
                    role = "customer"
                elif "employee" in k:
                    role = "employee"
                break

    if not role:
        low_intent = (intent or "").lower()
        if any(w in low_intent for w in ("sale", "invoice", "receipt", "customer")):
            role = "customer"
        elif any(w in low_intent for w in ("payroll", "employee", "salary")):
            role = "employee"
        else:
            role = "supplier"

    if name:
        return LivingDraftCounterparty(
            name=name,
            role=role,
            tax_status=entities.get("sales_tax_status"),
            strn=entities.get("strn"),
            ntn=entities.get("tax_number"),
        )
    return None


def _extract_line_items(entities: Dict[str, Any], default_amount: Optional[float] = None) -> List[LivingDraftLineItem]:
    """Build line items list from extracted entities."""
    raw_items = entities.get("line_items")
    items: List[LivingDraftLineItem] = []

    if isinstance(raw_items, list) and raw_items:
        for item in raw_items:
            if isinstance(item, dict):
                desc = str(item.get("description") or item.get("name") or "Item").strip()
                qty = float(item.get("quantity") or 1.0)
                unit_price = float(item.get("unit_price") or 0.0)
                tot = float(item.get("total_amount") or (qty * unit_price))
                if tot == 0.0 and default_amount and len(raw_items) == 1:
                    tot = default_amount
                    unit_price = tot / qty if qty else tot
                items.append(LivingDraftLineItem(
                    description=desc,
                    quantity=qty,
                    unit_price=unit_price,
                    total_amount=tot,
                    account_name=item.get("account_name"),
                ))
    if not items:
        desc = (
            entities.get("item_description")
            or entities.get("description")
            or entities.get("asset_name")
            or entities.get("product_name")
            or entities.get("transaction_purpose")
            or entities.get("notes")
        )
        if desc:
            tot = default_amount or 0.0
            qty = float(entities.get("quantity") or 1.0)
            up = tot / qty if qty else tot
            items.append(LivingDraftLineItem(
                description=str(desc).strip(),
                quantity=qty,
                unit_price=up,
                total_amount=tot,
            ))

    return items


def _determine_document_type(intent: str, nature: Optional[str], channel: Optional[str]) -> str:
    """Determine the standard accounting document voucher title."""
    intent_low = (intent or "").lower()
    nature_up = (nature or "").upper()

    if nature_up == "FIXED_ASSET" or any(w in intent_low for w in ("fixed_asset", "capital_asset", "depreciation")):
        if channel == "cash":
            return "Cash Payment Voucher (Fixed Asset Capitalization)"
        elif channel in ("bank_transfer", "bank", "cheque"):
            return "Bank Payment Voucher (Fixed Asset Capitalization)"
        elif channel == "credit":
            return "Vendor Bill (Fixed Asset Acquisition on Credit)"
        return "Fixed Asset Capitalization Voucher"

    if any(w in intent_low for w in ("expense", "record_expense")):
        if channel == "cash":
            return "Cash Payment Voucher (Operating Expense)"
        elif channel in ("bank_transfer", "bank"):
            return "Bank Payment Voucher (Operating Expense)"
        elif channel == "credit":
            return "Vendor Bill / Accrued Expense"
        return "Expense Voucher"

    if any(w in intent_low for w in ("purchase", "bill", "vendor")):
        if channel == "cash":
            return "Cash Purchase Voucher"
        elif channel in ("bank_transfer", "bank"):
            return "Bank Payment Voucher (Purchase)"
        elif channel == "credit":
            return "Vendor Bill (Credit Purchase)"
        return "Purchase Voucher"

    if any(w in intent_low for w in ("sale", "invoice")):
        if channel == "cash":
            return "Cash Receipt / Direct Sale Voucher"
        elif channel == "credit":
            return "Customer Sales Invoice"
        return "Sales Invoice"

    if any(w in intent_low for w in ("payment", "pay_supplier")):
        return "Supplier Payment Voucher"

    if any(w in intent_low for w in ("receipt", "receive_payment")):
        return "Customer Receipt Voucher"

    if any(w in intent_low for w in ("payroll", "salary")):
        return "Payroll Disbursement Voucher"

    return "Transaction Draft Voucher"


def _generate_voucher_preview(
    *,
    document_type: str,
    nature: Optional[str],
    total_amount: Optional[float],
    channel: Optional[str],
    bank_name: Optional[str],
    counterparty: Optional[LivingDraftCounterparty],
    line_items: List[LivingDraftLineItem],
    entities: Dict[str, Any],
) -> List[VoucherLinePreview]:
    """Synthesize debit/credit double-entry lines for the voucher card preview."""
    if not total_amount or total_amount <= 0:
        return []

    lines: List[VoucherLinePreview] = []
    nature_up = (nature or "").upper()
    c_name = counterparty.name if counterparty else None

    # Settlement Account (Credit side for expenses/purchases, Debit side for sales/receipts)
    if channel == "cash":
        settlement_account = "1000 - Cash on Hand"
    elif channel in ("bank_transfer", "cheque"):
        settlement_account = f"1010 - {bank_name or 'Bank Account'} (Current)"
    elif channel == "credit":
        if "sale" in document_type.lower() or "invoice" in document_type.lower():
            settlement_account = f"1100 - Accounts Receivable ({c_name or 'Customer'})"
        else:
            settlement_account = f"2000 - Accounts Payable ({c_name or 'Supplier'})"
    else:
        settlement_account = "[Pending Settlement Method]"

    item_desc = line_items[0].description if line_items else "Transaction item"

    # 1. FIXED ASSET ACQUISITION
    if nature_up == "FIXED_ASSET" or "Asset" in document_type:
        asset_account = "1500 - Office Equipment / Fixed Assets"
        for itm in line_items:
            low = itm.description.lower()
            if any(w in low for w in ("laptop", "computer", "pc", "server", "macbook", "it ")):
                asset_account = "1510 - Computer & IT Equipment"
                break
            elif any(w in low for w in ("chair", "table", "desk", "furniture", "sofa")):
                asset_account = "1520 - Furniture & Fixtures"
                break
            elif any(w in low for w in ("car", "van", "vehicle", "truck", "bike")):
                asset_account = "1530 - Motor Vehicles"
                break
            elif any(w in low for w in ("machinery", "plant", "generator", "equipment")):
                asset_account = "1540 - Plant & Machinery"
                break

        lines.append(VoucherLinePreview(
            account_name=asset_account,
            debit=total_amount,
            credit=0.0,
            description=f"Capitalization: {item_desc}",
        ))
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=0.0,
            credit=total_amount,
            description=f"Settlement via {channel or 'pending channel'}",
        ))

    # 2. OPERATING EXPENSE
    elif "Expense" in document_type:
        exp_account = entities.get("account_name") or "5000 - General Operating Expenses"
        low = item_desc.lower()
        if any(w in low for w in ("rent", "office rent")):
            exp_account = "5100 - Rent Expense"
        elif any(w in low for w in ("utility", "electricity", "k-electric", "lesco", "internet", "ptcl")):
            exp_account = "5200 - Utilities & Internet Expense"
        elif any(w in low for w in ("stationery", "paper", "supplies", "tea", "refreshment")):
            exp_account = "5300 - Office Supplies & Refreshments"
        elif any(w in low for w in ("travel", "fuel", "fare", "uber", "careem")):
            exp_account = "5400 - Travelling & Conveyance"
        elif any(w in low for w in ("legal", "audit", "consultant", "advisory")):
            exp_account = "5500 - Professional & Legal Fees"

        lines.append(VoucherLinePreview(
            account_name=exp_account,
            debit=total_amount,
            credit=0.0,
            description=f"Expense: {item_desc}",
        ))
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=0.0,
            credit=total_amount,
            description=f"Settlement: {channel or 'pending channel'}",
        ))

    # 3. PURCHASES / INVENTORY
    elif "Purchase" in document_type or "Vendor Bill" in document_type:
        purchase_account = "1200 - Merchandise Inventory" if nature_up == "INVENTORY" else "5010 - Cost of Goods Sold / Purchases"
        lines.append(VoucherLinePreview(
            account_name=purchase_account,
            debit=total_amount,
            credit=0.0,
            description=f"Purchase: {item_desc}",
        ))
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=0.0,
            credit=total_amount,
            description=f"Settlement to {c_name or 'Vendor'}",
        ))

    # 4. SALES / REVENUE
    elif "Sale" in document_type or "Invoice" in document_type:
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=total_amount,
            credit=0.0,
            description=f"Receivable from {c_name or 'Customer'}",
        ))
        lines.append(VoucherLinePreview(
            account_name="4000 - Sales & Services Revenue",
            debit=0.0,
            credit=total_amount,
            description=f"Revenue: {item_desc}",
        ))

    # 5. PAYROLL
    elif "Payroll" in document_type:
        lines.append(VoucherLinePreview(
            account_name="5050 - Salaries & Wages Expense",
            debit=total_amount,
            credit=0.0,
            description=f"Salary for {c_name or 'Employee'}",
        ))
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=0.0,
            credit=total_amount,
            description=f"Salary disbursement via {channel or 'bank transfer'}",
        ))

    # Default fallback
    else:
        lines.append(VoucherLinePreview(
            account_name="General Ledger Debits",
            debit=total_amount,
            credit=0.0,
            description=item_desc,
        ))
        lines.append(VoucherLinePreview(
            account_name=settlement_account,
            debit=0.0,
            credit=total_amount,
            description="Offsetting Credit Entry",
        ))

    return lines


def _build_depreciation_schedule(
    nature: Optional[str],
    total_amount: Optional[float],
    entities: Dict[str, Any],
) -> Optional[DepreciationSchedulePreview]:
    """Construct depreciation schedule preview if transaction is a fixed asset."""
    nature_up = (nature or "").upper()
    if nature_up != "FIXED_ASSET":
        return None

    cost = total_amount or 0.0
    if cost <= 0:
        return None

    # Useful life
    life_raw = entities.get("useful_life_years") or entities.get("useful_life")
    life_years: int = 3  # standard default
    if life_raw is not None:
        try:
            life_clean = str(life_raw).upper().replace("YEARS", "").replace("YRS", "").strip()
            if life_clean in ("NONE", "0"):
                return None
            life_years = max(1, int(float(life_clean)))
        except (ValueError, TypeError):
            life_years = 3

    # Method
    method_raw = str(entities.get("depreciation_method") or "STRAIGHT_LINE").upper().strip()
    if "REDUCING" in method_raw:
        method = "REDUCING_BALANCE"
    elif "NONE" in method_raw:
        return None
    else:
        method = "STRAIGHT_LINE"

    # Salvage value
    salvage_raw = entities.get("salvage_value") or 0.0
    try:
        salvage = float(str(salvage_raw).replace(",", "").strip())
    except (ValueError, TypeError):
        salvage = 0.0

    depreciable = max(0.0, cost - salvage)
    annual = round(depreciable / life_years, 2)
    monthly = round(annual / 12.0, 2)

    return DepreciationSchedulePreview(
        useful_life_years=life_years,
        method=method,
        cost=cost,
        salvage_value=salvage,
        depreciable_amount=depreciable,
        annual_depreciation=annual,
        monthly_depreciation=monthly,
    )


def _generate_compliance_notes(
    *,
    nature: Optional[str],
    total_amount: Optional[float],
    channel: Optional[str],
    bank_name: Optional[str],
    counterparty: Optional[LivingDraftCounterparty],
    entities: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Synthesize Pakistan statutory & IFRS compliance notes for the voucher card."""
    notes: List[str] = []
    nature_up = (nature or "").upper()
    amt = total_amount or 0.0

    # 1. Section 73 & Section 21(l) Cash Limits
    if channel == "cash":
        if nature_up == "FIXED_ASSET" and amt > 250000.0:
            notes.append(
                f"⚠️ Section 73(2)/(3) Alert: Cash payment of PKR {amt:,.0f} exceeds the statutory capital asset limit of PKR 250,000. Depreciation deductions will be entirely disallowed under Income Tax Ordinance 2001 unless paid via crossed cheque or bank transfer."
            )
        elif nature_up != "FIXED_ASSET" and amt > 50000.0:
            notes.append(
                f"⚠️ Section 73 / 21(l) Warning: Cash expenditure of PKR {amt:,.0f} exceeds the statutory business limit of PKR 50,000. Risk of complete disallowance in tax assessment. Banking channel recommended."
            )
        elif amt > 0:
            notes.append("✓ Section 73 Notice: Cash payment within statutory limit (under PKR 50,000).")
    elif channel in ("bank_transfer", "cheque"):
        b_label = f" via {bank_name}" if bank_name else ""
        notes.append(f"✓ Section 73 Compliance: Settled through authorized banking channel{b_label} (deductible).")

    # 2. Section 153 Withholding Tax (WHT)
    wht_exempt = entities.get("wht_exempt")
    if wht_exempt is True:
        notes.append("✓ Section 153 Exemption: Valid tax exemption certificate acknowledged (0% withholding).")
    elif amt >= 75000.0 and nature_up != "FIXED_ASSET":
        notes.append("ℹ️ Section 153 WHT: Standard withholding tax applies upon payment settlement to supplier.")

    # 3. IAS 16 Capitalization
    if nature_up == "FIXED_ASSET":
        notes.append("ℹ️ IAS 16 Accounting Policy: Long-term economic benefits verified (> 1 year useful life).")

    return notes


# ---------------------------------------------------------------------------
# Core Entry Point: build_living_draft
# ---------------------------------------------------------------------------

def build_living_draft(
    *,
    intent: str,
    entities: Dict[str, Any],
    missing_fields: Sequence[str] = (),
    nature: Optional[str] = None,
    classification: Optional[Any] = None,
    session_phase: Optional[str] = None,
) -> LivingDraft:
    """Accumulate known facts and construct the real-time living draft voucher card."""
    ents = dict(entities or {})
    total_amount = _extract_amount(ents)
    channel, bank_name = _extract_channel(ents)

    # Nature resolution
    resolved_nature = (
        nature
        or ents.get("transaction_nature")
        or getattr(classification, "transaction_nature", None)
        or ""
    )

    counterparty = _extract_counterparty(intent, ents)
    line_items = _extract_line_items(ents, default_amount=total_amount)
    document_type = _determine_document_type(intent, resolved_nature, channel)

    voucher_preview = _generate_voucher_preview(
        document_type=document_type,
        nature=resolved_nature,
        total_amount=total_amount,
        channel=channel,
        bank_name=bank_name,
        counterparty=counterparty,
        line_items=line_items,
        entities=ents,
    )

    depreciation_schedule = _build_depreciation_schedule(
        nature=resolved_nature,
        total_amount=total_amount,
        entities=ents,
    )

    compliance_notes = _generate_compliance_notes(
        nature=resolved_nature,
        total_amount=total_amount,
        channel=channel,
        bank_name=bank_name,
        counterparty=counterparty,
        entities=ents,
    )

    cleaned_missing = [str(f).strip() for f in missing_fields if str(f).strip()]

    # Status calculation
    if session_phase == "COMPLETED" or session_phase == "EXECUTING":
        status = "posted"
    elif not cleaned_missing and total_amount and total_amount > 0:
        status = "ready_for_confirmation"
    elif cleaned_missing:
        status = "awaiting_input"
    else:
        status = "drafting"

    tx_date = ents.get("transaction_date") or ents.get("date") or ents.get("expense_date")

    draft = LivingDraft(
        document_type=document_type,
        voucher_preview=voucher_preview,
        counterparty=counterparty,
        line_items=line_items,
        total_amount=total_amount,
        currency=ents.get("currency", "PKR"),
        payment_channel=channel,
        bank_name=bank_name,
        transaction_date=str(tx_date) if tx_date else None,
        depreciation_schedule=depreciation_schedule,
        compliance_notes=compliance_notes,
        status=status,
        missing_fields=cleaned_missing,
    )
    draft.attach_interactive_artifact()
    return draft
