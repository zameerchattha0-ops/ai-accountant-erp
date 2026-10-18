"""Verify live catalogue linkage for inventory purchases (2026-10-18)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import fetch_many

ORG = "4f20f43c-bb3b-4747-abe1-02d9380884df"


async def main() -> None:
    prods = await fetch_many(
        "products",
        filters={"organization_id": ORG},
        select="name,product_code,is_stock_tracked,cost_price",
        limit=50,
    )
    print("=== PRODUCTS ===")
    for p in prods or []:
        print(" ", p)
    print("=== INVENTORY MOVEMENTS (latest 8) ===")
    mv = await fetch_many(
        "inventory_movements",
        filters={"organization_id": ORG},
        select="direction,quantity,unit_cost,source_type,description,product_id,created_at",
        order="created_at.desc",
        limit=8,
    )
    for m in mv or []:
        print(" ", m)
    print("=== BILL ITEMS (latest 4 purchase bills) ===")
    bills = await fetch_many(
        "purchase_bills",
        filters={"organization_id": ORG},
        select="bill_number,total,notes,items",
        order="created_at.desc",
        limit=4,
    )
    for b in bills or []:
        print(" ", b.get("bill_number"), b.get("total"), "items=", b.get("items"))


if __name__ == "__main__":
    import traceback

    try:
        asyncio.run(main())
    except Exception:
        with open(r"E:\Qoder\Ai Accountant\ERP\scripts\_stock_exc.txt", "w") as fh:
            fh.write(traceback.format_exc())
        raise
