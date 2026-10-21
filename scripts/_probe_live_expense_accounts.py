import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uuid
from app.database import fetch_many

ORG = uuid.UUID("00000000-0000-4000-8000-000000000010")

async def main():
    rows = await fetch_many("accounts", filters={"organization_id": ORG}, limit=200)
    expenses = [r for r in rows if r.get("account_type") == "EXPENSE"]
    print(f"Total accounts: {len(rows)}, Expense accounts: {len(expenses)}")
    for e in sorted(expenses, key=lambda x: str(x.get("code") or "")):
        print(f"  {e.get('code')} - {e.get('name')} (is_active={e.get('is_active')}, is_control={e.get('is_control_account')}, id={e.get('id')})")

if __name__ == "__main__":
    asyncio.run(main())

