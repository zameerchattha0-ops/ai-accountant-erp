# Baseline snapshot — uncommitted working state (2026-10-16)

> **SUPERSEDED BY COMMIT `e383e82`** (`e383e82977c7d99ad397083b2421f33bb74aa1e3`)
> — the SHA is now the code baseline; this file is retained as its own
> artifact so the pre-commit state stays independently verifiable.

Purpose: reproducible identification of the exact source state validated at
**1,165 passing tests** BEFORE any commit exists — the interim substitute
for a baseline SHA (checked plan, Baseline & reproducibility block). A
commit supersedes this file; until then this is the reference artifact.

## Verification

Diff hash (self-consistent with its capture method — PowerShell `>`
redirection applies its own encoding; reproduce with the same tooling):

```powershell
cd 'e:\Qoder\Ai Accountant\ERP'
git diff > $env:TEMP\wip_baseline.diff
git hash-object $env:TEMP\wip_baseline.diff   # must equal: baabde1cac3743462a3351d847bdfc0beee35539
```

Per-file hashes — BYTE-EXACT against the baseline commit (verified
2026-10-16: all four OK). NOTE: `git show <sha>:<path> | git hash-object
--stdin` through a PowerShell pipeline MANGLES bytes (encoding
conversion) and produces false mismatches — use raw subprocess bytes:

```python
import subprocess, hashlib
blob = subprocess.run(
    ["git", "cat-file", "blob", "e383e82:app/tests/test_llm_adversarial_cases.py"],
    capture_output=True,
).stdout
print(hashlib.sha1(blob).hexdigest())   # 7fff28b1a30f4e69a3397fb1fa563728ad968295
```

## Session-owned changes (the work under this plan)

Tracked modifications (covered by the diff hash above):
- `app/agent.py` (two-call hoist, hint gate, telemetry)
- `app/entity_segregation.py` (Fix A purpose intake + prompt scope)
- `app/llm_classification.py` (CALL 2 scope docstring)
- `app/main.py` (health flag echo)
- `app/planner.py` (purpose prefill gate)
- `app/questionnaire.py` (applicable-filter + SYSTEM_CONTEXT)
- `docs/LATENCY_QUERIES.sql` (§10/10b/10c/11)

New (untracked — verified by SHA1, excluded from the diff hash):
- `app/tests/test_two_call_restructure.py` → `2287e4550d5ee1939d8895d38ee63cf358f07cb3`
- `app/tests/test_llm_adversarial_cases.py` → `7fff28b1a30f4e69a3397fb1fa563728ad968295`
- `docs/LLM_PRIMARY_IMPLEMENTATION_PLAN.md` → `985e9ae63a76f40c978073a2fe90ae7b16642da6`
- `scripts/residual_shape_probe.py` → `957a03d8e04b95f5ab6cc97381b4b5058765fb31`

Outside any git repository (baseline must note this — cannot be committed
to ERP): `e:\Qoder\MASTER_PROMPT.md` → `d8621a543f4f1d755913c301b91d6b61b8b04bb2`

## NOT session-owned (pre-existing dirty state — exclude from any commit)

- `M frontend/src/app/welcome/page.tsx`
- untracked: `_trail_elec.json`, `_trail_elec2.json`, `_trail_party.json`,
  `frontend/_eslint*`, `frontend/_tsc*`,
  `frontend/src/components/hero/NavyHero.tsx`, `out.txt`, `out2.txt`,
  `scripts/_diag_elec_exec.py`

## Reproduce the suite gate

```powershell
python -m pytest app/tests -q --no-header --ignore=app/tests/test_provider_rate_limit_fallback.py
# expected: 1165 passed
```

This file intentionally does not hash itself; refresh hashes if any listed
file changes after capture.
