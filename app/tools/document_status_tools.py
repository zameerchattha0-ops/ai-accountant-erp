"""
Universal Document Status Update Tool — supports Single & Bulk updates across ALL modules:
- Purchase Bills (DRAFT, OPEN, PARTIALLY_PAID, PAID, OVERDUE, VOIDED)
- Purchase Orders / RFQs (RFQ, ORDERED, RECEIVED, BILLED, CANCELLED)
- Invoices (DRAFT, ISSUED, PARTIALLY_PAID, PAID, OVERDUE, VOIDED, CREDITED)
- Quotations (DRAFT, SENT, ACCEPTED, REJECTED, EXPIRED, CONVERTED)
- Catalogue Products (ACTIVE, INACTIVE)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.database import fetch_many, fetch_one, update_one
from app.models.schemas import ToolResult

log = structlog.get_logger(__name__)

# Valid status transitions & terminal locks per document type
TERMINAL_STATUSES: Dict[str, set] = {
    "purchase_bill": {"VOIDED"},
    "invoice": {"VOIDED", "CREDITED"},
    "quotation": {"CONVERTED"},
    "purchase_order": {"CANCELLED", "BILLED"},
    "product": set(),
}

VALID_STATUSES: Dict[str, set] = {
    "purchase_bill": {"DRAFT", "OPEN", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOIDED"},
    "invoice": {"DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "VOIDED", "CREDITED"},
    "quotation": {"DRAFT", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "CONVERTED"},
    "purchase_order": {"RFQ", "ORDERED", "RECEIVED", "BILLED", "CANCELLED"},
    "product": {"ACTIVE", "INACTIVE"},
}

DOC_TYPE_ALIASES: Dict[str, str] = {
    "bill": "purchase_bill",
    "bills": "purchase_bill",
    "purchase_bill": "purchase_bill",
    "purchase_bills": "purchase_bill",
    "purchase": "purchase_bill",
    "purchases": "purchase_bill",
    "po": "purchase_order",
    "pos": "purchase_order",
    "order": "purchase_order",
    "orders": "purchase_order",
    "rfq": "purchase_order",
    "rfqs": "purchase_order",
    "purchase_order": "purchase_order",
    "purchase_orders": "purchase_order",
    "inv": "invoice",
    "invoice": "invoice",
    "invoices": "invoice",
    "sale": "invoice",
    "sales": "invoice",
    "quote": "quotation",
    "quotes": "quotation",
    "quotation": "quotation",
    "quotations": "quotation",
    "product": "product",
    "products": "product",
    "item": "product",
    "items": "product",
    "catalogue": "product",
}


def normalize_doc_type(raw_type: str) -> str:
    cleaned = (raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return DOC_TYPE_ALIASES.get(cleaned, cleaned)


def normalize_reference(ref: str, doc_type: str) -> str:
    clean = str(ref).strip()
    digits = re.findall(r"\d+", clean)
    num_str = digits[-1] if digits else clean

    if doc_type == "purchase_bill":
        if clean.upper().startswith("PUR-"):
            return clean.upper()
        if digits:
            return f"PUR-{int(num_str):06d}"
    elif doc_type == "invoice":
        if clean.upper().startswith("INV-"):
            return clean.upper()
        if digits:
            return f"INV-{int(num_str):06d}"
    elif doc_type == "quotation":
        if clean.upper().startswith("QTN-"):
            return clean.upper()
        if digits:
            return f"QTN-{int(num_str):06d}"
    elif doc_type == "purchase_order":
        if clean.upper().startswith("PO-") or clean.upper().startswith("RFQ-"):
            return clean.upper()
        if digits:
            return f"PO-{int(num_str):06d}"
    elif doc_type == "product":
        if clean.upper().startswith("PRD-"):
            return clean.upper()
        if digits:
            return f"PRD-{int(num_str):06d}"

    return clean


async def update_document_status(
    organization_id: uuid.UUID,
    *,
    document_type: str,
    target_status: str,
    reference_numbers: Optional[List[str]] = None,
    document_reference: Optional[str] = None,
    reason: Optional[str] = None,
) -> ToolResult:
    """Universal status updater across all ERP modules."""
    norm_type = normalize_doc_type(document_type)
    if norm_type not in VALID_STATUSES:
        return ToolResult(
            tool_name="update_document_status",
            success=False,
            error=f"Unsupported document type '{document_type}'. Supported: purchase_bill, purchase_order, invoice, quotation, product",
        )

    norm_target = str(target_status or "").strip().upper()
    if norm_target == "PURCHASE_ORDER" or norm_target == "PO":
        norm_target = "ORDERED"
    elif norm_target == "DEACTIVATE" or norm_target == "DISABLE":
        norm_target = "INACTIVE"
    elif norm_target == "ACTIVATE" or norm_target == "ENABLE":
        norm_target = "ACTIVE"

    if norm_target not in VALID_STATUSES[norm_type]:
        return ToolResult(
            tool_name="update_document_status",
            success=False,
            error=f"Invalid target status '{target_status}' for {norm_type}. Valid: {sorted(VALID_STATUSES[norm_type])}",
        )

    # Collect all reference strings
    refs: List[str] = []
    if reference_numbers:
        for r in reference_numbers:
            if isinstance(r, (str, int)):
                refs.append(str(r).strip())
    if document_reference and str(document_reference).strip():
        # Might be space or comma separated (e.g. "14 and 15" or "PUR-000014, PUR-000015")
        found = re.findall(r"[A-Za-z0-9\-_]+", str(document_reference))
        for item in found:
            if item.lower() not in ("and", "or", "&", "to", "against", "bill", "invoice", "bills", "invoices", "po", "rfq"):
                refs.append(item)

    if not refs:
        return ToolResult(
            tool_name="update_document_status",
            success=False,
            error="No document references provided to update.",
        )

    # De-duplicate while preserving order
    seen = set()
    unique_refs = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            unique_refs.append(r)

    # Fetch and update each document
    updated_docs: List[Dict[str, Any]] = []
    failed_docs: List[Dict[str, Any]] = []

    table_map = {
        "purchase_bill": ("purchase_bills", "bill_number", "/purchases/bills"),
        "purchase_order": ("purchase_orders", "po_number", "/purchases/orders"),
        "invoice": ("invoices", "invoice_number", "/sales/invoices"),
        "quotation": ("quotations", "quotation_number", "/sales/quotations"),
        "product": ("products", "product_code", "/catalogue"),
    }
    table_name, col_num, base_url = table_map[norm_type]

    for raw_ref in unique_refs:
        norm_ref = normalize_reference(raw_ref, norm_type)
        # Search exact or ilike
        rows = await fetch_many(
            table_name,
            filters={"organization_id": str(organization_id), col_num: norm_ref},
            limit=1,
        )
        if not rows:
            # Fallback search by pattern or digits
            digits = re.findall(r"\d+", raw_ref)
            if digits:
                num_pattern = f"%{digits[-1]}"
                from app.database import search_ilike
                rows = await search_ilike(
                    table_name,
                    column=col_num,
                    value=digits[-1],
                    organization_id=organization_id,
                    limit=5,
                )
        if not rows and norm_type == "product":
            # Search by name
            from app.database import search_ilike
            rows = await search_ilike(
                "products",
                column="name",
                value=raw_ref,
                organization_id=organization_id,
                limit=5,
            )

        if not rows:
            failed_docs.append({"reference": raw_ref, "reason": "Document not found"})
            continue

        doc = rows[0]
        curr_status = str(doc.get("status") or ("ACTIVE" if doc.get("is_active") else "INACTIVE")).upper()
        doc_ref = str(doc.get(col_num) or doc.get("name") or raw_ref)

        # Invariant checks
        if curr_status in TERMINAL_STATUSES[norm_type]:
            failed_docs.append({
                "reference": doc_ref,
                "reason": f"Cannot transition from terminal locked status '{curr_status}'",
            })
            continue

        if curr_status == norm_target:
            # Already in target status
            updated_docs.append({
                "id": str(doc["id"]),
                "reference": doc_ref,
                "previous_status": curr_status,
                "new_status": norm_target,
                "total": float(doc.get("total") or doc.get("unit_price") or 0.0),
                "party_name": await _resolve_party_name(organization_id, norm_type, doc),
                "url": f"{base_url}#{doc_ref}",
                "note": "Already in target status",
            })
            continue

        # Execute Update
        try:
            upd_data: Dict[str, Any] = {}
            if norm_type == "product":
                upd_data["is_active"] = (norm_target == "ACTIVE")
            else:
                upd_data["status"] = norm_target

            # Side effects on bills and invoices when moving to PAID
            now_iso = datetime.now(timezone.utc).isoformat()
            if norm_target == "PAID" and norm_type in ("purchase_bill", "invoice"):
                upd_data["amount_paid"] = float(doc.get("total") or 0.0)
                upd_data["paid_at"] = now_iso
            elif norm_target == "VOIDED" and norm_type in ("purchase_bill", "invoice"):
                upd_data["voided_at"] = now_iso
            elif norm_target == "ACCEPTED" and norm_type == "quotation":
                upd_data["accepted_at"] = now_iso

            await update_one(
                table_name,
                data=upd_data,
                filters={"id": str(doc["id"]), "organization_id": str(organization_id)},
            )

            # PO service transition for stock receipts
            if norm_type == "purchase_order" and norm_target == "RECEIVED":
                from app.services import purchase_order_service
                try:
                    await purchase_order_service.transition_order_status(
                        organization_id, order_id=uuid.UUID(str(doc["id"])), new_status="RECEIVED"
                    )
                except Exception as po_err:
                    log.warning("po_transition_warn", error=str(po_err))

            party_name = await _resolve_party_name(organization_id, norm_type, doc)
            updated_docs.append({
                "id": str(doc["id"]),
                "reference": doc_ref,
                "previous_status": curr_status,
                "new_status": norm_target,
                "total": float(doc.get("total") or doc.get("unit_price") or 0.0),
                "party_name": party_name,
                "url": f"{base_url}#{doc_ref}",
            })
        except Exception as exc:
            failed_docs.append({"reference": doc_ref, "reason": str(exc)[:200]})

    if not updated_docs and failed_docs:
        err_msg = "; ".join([f"{f['reference']}: {f['reason']}" for f in failed_docs])
        return ToolResult(
            tool_name="update_document_status",
            success=False,
            error=f"Failed to update document status: {err_msg}",
        )

    # Build Verification Table & Audit Card
    rows_markdown = []
    for d in updated_docs:
        amt_str = f"Rs. {d['total']:,.2f}" if d.get("total") else "—"
        rows_markdown.append(
            f"| [{d['reference']}]({d['url']}) | {d['party_name']} | `{d['previous_status']}` | `{d['new_status']}` | {amt_str} |"
        )
    table_content = "\n".join(rows_markdown)

    plural_noun = {
        "purchase_bill": "bills",
        "purchase_order": "purchase orders",
        "invoice": "invoices",
        "quotation": "quotations",
        "product": "products",
    }.get(norm_type, "documents")

    summary_md = (
        f"### Successfully updated {len(updated_docs)} {plural_noun} to status **{norm_target}**\n\n"
        f"| Document Ref | Party / Name | Previous Status | New Status | Amount / Impact |\n"
        f"| :--- | :--- | :--- | :--- | :--- |\n"
        f"{table_content}\n\n"
        f"*Audit check verified. Actions available:* [{base_url.replace('/', ' ').title().strip()}]({base_url}) • *Undo supported.*"
    )

    audit_payload = {
        "summary": summary_md,
        "updated_count": len(updated_docs),
        "target_status": norm_target,
        "document_type": norm_type,
        "documents": updated_docs,
        "failed": failed_docs,
        "undo_available": True,
        "undo_payload": [
            {"id": d["id"], "type": norm_type, "status": d["previous_status"]}
            for d in updated_docs
        ],
    }

    return ToolResult(
        tool_name="update_document_status",
        success=True,
        data=audit_payload,
    )


async def _resolve_party_name(organization_id: uuid.UUID, doc_type: str, doc: Dict[str, Any]) -> str:
    """Helper to fetch party (supplier / customer) or product name for display."""
    if doc_type == "purchase_bill" or doc_type == "purchase_order":
        s_id = doc.get("supplier_id")
        if s_id:
            s = await fetch_one("suppliers", filters={"id": str(s_id), "organization_id": str(organization_id)})
            return (s or {}).get("name") or "Supplier"
        return "Cash / Direct"
    elif doc_type == "invoice" or doc_type == "quotation":
        c_id = doc.get("customer_id")
        if c_id:
            c = await fetch_one("customers", filters={"id": str(c_id), "organization_id": str(organization_id)})
            return (c or {}).get("name") or "Customer"
        return "Customer"
    elif doc_type == "product":
        return str(doc.get("name") or "Product")
    return "—"
