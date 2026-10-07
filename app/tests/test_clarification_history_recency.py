"""Regression: clarification history must be RECENCY-FIRST, not oldest-first.

Production failure (AES Engineering, 2026-10-06 — sessions aa041df4 …
7951a863): every answered clarification re-enters ``execute()`` under a NEW
session row and ``seed_clarification_history`` bulk-copies prior Q&A into
it, so one conversation accumulated 42 ``ai.clarifications`` rows per
session.  The ``revenue_ledger_decision`` gate is asked LAST (row 41/42),
but ``get_clarification_history`` read ``created_at ASC LIMIT 20`` — the
OLDEST twenty — so the revenue answer NEVER reached the planner:

  * ``needs_review()`` (3 revenue accounts in the AES chart) re-asked the
    gate on every resume;
  * 6 sessions looped, 0 ``tool_calls`` rows were ever written;
  * the child revenue ledger under the default parent was never created.

Pinned invariants:
  * the read is newest-first (``created_at.desc``) with a cap that fits a
    realistic conversation (>= 200 rows);
  * the returned history is CHRONOLOGICAL (later answers merge last);
  * the last-asked/last-answered question (revenue gate) survives even
    when the session holds far more rows than the cap;
  * exact duplicate Q&A pairs (the seed re-inserts them every round) are
    collapsed, but same-question/different-answer pairs both survive;
  * ``required_information`` rides along verbatim (positional field tags).
"""

import uuid

import pytest

import app.database as db

SESSION = uuid.UUID("11111111-1111-1111-1111-111111111111")

REVENUE_Q = (
    "Revenue ledger check: nothing is recorded against 'Fibre Doors' yet. "
    "Create a dedicated ledger 'Fibre Doors Sales' under 'Operating Revenue' "
    "so this revenue is reported separately?"
)


def _row(question, answer, fields=None, created_at="2026-10-06T09:51:00+00:00"):
    return {
        "question": question,
        "user_response": answer,
        "required_information": fields or [],
        "created_at": created_at,
    }


class _Capture:
    """fetch_many stand-in: records the call, serves rows newest-first."""

    def __init__(self, rows_desc):
        self.rows_desc = rows_desc
        self.calls = []

    async def __call__(self, table_name, *, filters, select="*", order=None,
                       limit=100, offset=0):
        self.calls.append(
            {"table": table_name, "filters": filters, "order": order,
             "limit": limit}
        )
        return (self.rows_desc or [])[:limit]


class TestRecencyFirstRead:
    @pytest.mark.asyncio
    async def test_orders_newest_first_with_a_generous_cap(self, monkeypatch):
        cap = _Capture([])
        monkeypatch.setattr(db, "fetch_many", cap)

        await db.get_clarification_history(SESSION)

        assert len(cap.calls) == 1
        call = cap.calls[0]
        assert call["table"] == "ai_clarifications"
        assert call["order"] == "created_at.desc", (
            "oldest-first reads drop the LAST-asked answer — the exact "
            "production bug that looped the AES revenue gate forever"
        )
        assert call["limit"] >= 200, "a 42-row session must fit entirely"
        assert call["filters"]["status"] == "COMPLETED"
        assert call["filters"]["execution_session_id"] == str(SESSION)

    @pytest.mark.asyncio
    async def test_late_revenue_answer_is_returned_last(self, monkeypatch):
        # NEWEST first, as the desc query returns: seeded copies of the
        # early rounds first-in-time (thus LAST here), the just-answered
        # revenue gate FIRST — the shape that defeated the old ASC read.
        rows = [
            _row(REVENUE_Q, "yes", ["revenue_ledger_decision"],
                 created_at="2026-10-06T09:54:24+00:00"),
            _row("Catalog check: 'Fibre Doors' is not in your catalog yet. "
                 "Add it?", "Yes - add to catalog",
                 created_at="2026-10-06T09:53:35+00:00"),
            _row("item_description", "Fibre Doors", ["item_description"],
                 created_at="2026-10-06T09:53:35+00:00"),
            _row("transaction_date", "TODAY", ["transaction_date"],
                 created_at="2026-10-06T09:53:35+00:00"),
        ]
        monkeypatch.setattr(db, "fetch_many", _Capture(rows))

        history = await db.get_clarification_history(SESSION)

        # chronological: earliest first, the revenue answer LAST so the
        # planner merges it and the gate resolves instead of re-asking
        assert [h["question"] for h in history] == [
            "transaction_date",
            "item_description",
            rows[1]["question"],
            REVENUE_Q,
        ]
        assert history[-1]["answer"] == "yes"
        assert history[-1]["required_information"] == ["revenue_ledger_decision"]

    @pytest.mark.asyncio
    async def test_answer_beyond_any_reasonable_cap_still_survives(
        self, monkeypatch
    ):
        # 60 seeded duplicates + the fresh answer, cap 200 → everything
        # fits; the fresh answer (newest = first row served) is kept.
        rows = [
            _row(REVENUE_Q, "Use the existing 'Operating Revenue' account",
                 ["revenue_ledger_decision"]),
            *[
                _row("item_description", "Fibre Doors",
                     ["item_description"],
                     created_at="2026-10-06T09:00:00+00:00")
                for _ in range(60)
            ],
        ]
        monkeypatch.setattr(db, "fetch_many", _Capture(rows))

        history = await db.get_clarification_history(SESSION)

        assert history[-1]["question"] == REVENUE_Q
        assert "Operating Revenue" in history[-1]["answer"]


class TestDedupeKeepsSemantics:
    @pytest.mark.asyncio
    async def test_exact_duplicate_pairs_collapse_to_one(self, monkeypatch):
        rows = [  # desc: seed copies of the SAME pair, three rounds deep
            _row("item_description", "Fibre Doors", ["item_description"]),
            _row("item_description", "Fibre Doors", ["item_description"]),
            _row("item_description", "Fibre Doors", ["item_description"]),
            _row("transaction_date", "TODAY", ["transaction_date"]),
        ]
        monkeypatch.setattr(db, "fetch_many", _Capture(rows))

        history = await db.get_clarification_history(SESSION)

        assert [(h["question"], h["answer"]) for h in history] == [
            ("transaction_date", "TODAY"),
            ("item_description", "Fibre Doors"),
        ]

    @pytest.mark.asyncio
    async def test_same_question_newer_answer_keeps_both(self, monkeypatch):
        # A re-asked question with a DIFFERENT answer must keep both rows:
        # chronological merge order lets the newer answer win.
        rows = [
            _row(REVENUE_Q, "yes"),          # newest (desc first)
            _row(REVENUE_Q, "Use the existing 'Operating Revenue' account"),
        ]
        monkeypatch.setattr(db, "fetch_many", _Capture(rows))

        history = await db.get_clarification_history(SESSION)

        assert [h["answer"] for h in history] == [
            "Use the existing 'Operating Revenue' account",
            "yes",
        ]

    @pytest.mark.asyncio
    async def test_empty_answer_rows_are_dropped(self, monkeypatch):
        rows = [
            _row(REVENUE_Q, ""),
            _row("transaction_date", "TODAY", ["transaction_date"]),
        ]
        monkeypatch.setattr(db, "fetch_many", _Capture(rows))

        history = await db.get_clarification_history(SESSION)

        assert len(history) == 1
        assert history[0]["question"] == "transaction_date"

    @pytest.mark.asyncio
    async def test_none_rows_tolerated(self, monkeypatch):
        monkeypatch.setattr(db, "fetch_many", _Capture(None))
        assert await db.get_clarification_history(SESSION) == []