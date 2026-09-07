"""
Document Item Validation — ONE shared contract for invoice/bill line items.

The PARITY LAW requires that the AI tool path and the manual UI path apply
IDENTICAL validation and identical line-total computation.  Both the
invoice service and the purchase service call ``validate_document_items``
so a line row can never be written by any path without passing the same
rules:

    * description  — non-empty
    * quantity     — > 0
    * unit_price   — >= 0
    * discount     — >= 0 and <= gross
    * line_total   — computed here (quantity × unit_price − discount
                     + tax), never trusted from the caller
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def validate_document_items(
    items: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Validate + normalise line items; compute every line_total.

    Returns ``(normalized_items, header_totals)`` where ``header_totals``
    carries ``subtotal`` (Σ quantity × unit_price), ``discount_total``,
    ``tax_total`` and ``total`` (subtotal − discount + tax) so the header
    row is ALWAYS arithmetically consistent with its lines.

    Raises ``ValueError`` with a precise message on the first invalid line —
    nothing is guessed and no line is silently dropped.
    """
    if not items:
        raise ValueError("At least one line item is required.")

    normalized: List[Dict[str, Any]] = []
    subtotal = 0.0
    discount_total = 0.0
    tax_total = 0.0

    for idx, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Line {idx}: each item must be an object.")

        description = str(raw.get("description") or "").strip()
        if not description:
            raise ValueError(f"Line {idx}: description is required.")

        try:
            quantity = float(raw.get("quantity", 0))
        except (TypeError, ValueError):
            raise ValueError(f"Line {idx}: quantity must be a number.")
        if quantity <= 0:
            raise ValueError(f"Line {idx}: quantity must be greater than 0.")

        try:
            unit_price = float(raw.get("unit_price", 0))
        except (TypeError, ValueError):
            raise ValueError(f"Line {idx}: unit_price must be a number.")
        if unit_price < 0:
            raise ValueError(f"Line {idx}: unit_price cannot be negative.")

        try:
            discount = float(raw.get("discount_amount", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Line {idx}: discount_amount must be a number.")
        if discount < 0:
            raise ValueError(f"Line {idx}: discount_amount cannot be negative.")

        try:
            tax = float(raw.get("tax_amount", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Line {idx}: tax_amount must be a number.")
        if tax < 0:
            raise ValueError(f"Line {idx}: tax_amount cannot be negative.")

        gross = quantity * unit_price
        if discount > gross:
            raise ValueError(
                f"Line {idx}: discount ({discount}) cannot exceed the "
                f"line amount ({gross})."
            )
        line_total = round(gross - discount + tax, 2)
        if line_total < 0:
            raise ValueError(f"Line {idx}: line_total cannot be negative.")

        normalized.append({
            "description": description,
            "product_id": raw.get("product_id") or None,
            "service_id": raw.get("service_id") or None,
            "project_id": raw.get("project_id") or None,
            "quantity": quantity,
            "unit_price": unit_price,
            "discount_amount": discount,
            "tax_rate_id": raw.get("tax_rate_id") or None,
            "tax_amount": tax,
            "line_total": line_total,
            # Purchases route lines to an expense/asset account; sales to a
            # revenue account.  Unknown keys are dropped — the repository
            # decides which columns exist for the target table.
            "expense_account_id": raw.get("expense_account_id") or None,
            "fixed_asset_id": raw.get("fixed_asset_id") or None,
            "revenue_account_id": raw.get("revenue_account_id") or None,
        })
        subtotal += gross
        discount_total += discount
        tax_total += tax

    totals = {
        "subtotal": round(subtotal, 2),
        "discount_total": round(discount_total, 2),
        "tax_total": round(tax_total, 2),
        "total": round(subtotal - discount_total + tax_total, 2),
    }
    return normalized, totals
