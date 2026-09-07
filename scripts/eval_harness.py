"""Work Stream K - CLI wrapper for the evaluation harness.

    venv\\Scripts\\python scripts\\eval_harness.py          # run, print pass-rate
    venv\\Scripts\\python scripts\\eval_harness.py --seed   # (re)write goldens
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.eval_harness import run, seed  # noqa: E402

if __name__ == "__main__":
    if "--seed" in sys.argv:
        print(f"Seeded {seed()} golden cases")
    rate = run()
    sys.exit(0 if rate >= 1.0 else 1)
