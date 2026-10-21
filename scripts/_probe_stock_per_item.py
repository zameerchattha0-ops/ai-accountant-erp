"""Read-only: prove v_product_stock is PER-ITEM (per product_id), never a
cross-item aggregate.  Prints every distinct product row with its own
quantity_on_hand / total_value / average_cost for the test org."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ERP_ROOT))

ORG = "00000000-0000-4000-8000-000000000010"


async def main() -> None:
    from app.database import fetch_many
    rows = await fetch_many(
        "v_product_stock",
        filters={"organization_id": ORG},
        select="product_id,product_code,name,quantity_on_hand,total_value,average_cost",
        limit=100,
    )
    print(f"DISTINCT PRODUCT ROWS (each = one tracked item): {len(rows)}\n")
    for r in sorted(rows, key=lambda x: str(x.get("name") or "")):
        print(f"  {r.get('product_code')}  {str(r.get('name'))!r:<40} "
              f"on_hand={r.get('quantity_on_hand'):<6} "
              f"value={r.get('total_value'):<10} avg_cost={r.get('average_cost')}")
    # explicit anti-aggregation proof: distinct products => distinct rows
    ids = {str(r.get("product_id")) for r in rows}
    print(f"\nunique product_ids == rows? {len(ids) == len(rows)} "
          f"({len(ids)} ids / {len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())
