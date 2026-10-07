import sqlite3
from pathlib import Path

db = next(Path(r'e:\Qoder\Ai Accountant\ERP\database').rglob('*.db'))
print("DB:", db)
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute('PRAGMA table_info(ai_clarifications)').fetchall()]
print("ai_clarifications cols:", cols)

rows = con.execute(
    """
    SELECT c.* FROM ai_clarifications c
    JOIN ai_execution_logs l ON l.session_id = c.session_id
    WHERE l.tool_name LIKE '%account%' OR l.tool_name LIKE '%revenue%' OR l.tool_name LIKE '%ledger%'
    ORDER BY c.created_at DESC LIMIT 50
    """
).fetchall()
for r in rows:
    d = dict(r)
    print('---')
    for k, v in d.items():
        s = str(v)
        print(f"  {k}: {s[:400]}")
con.close()