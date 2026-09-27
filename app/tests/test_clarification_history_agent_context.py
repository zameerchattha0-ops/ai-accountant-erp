"""Regression: ``AgentContext`` must accept the history the resume path
actually returns.

Live defect (2026-09-27, sessions ``2391071e-9bd4-4768-81d0-6cc29137f2d2``
and ``704e1fb3-eae8-4908-94fb-b001cb78dfe9``, intent ``register_fixed_asset``):
every RESUMED questionnaire turn (the depreciation / useful-life round of a
fixed-asset purchase) died with::

    2 validation errors for AgentContext
    clarification_history.0.required_information
      Input should be a valid string [..., input_value=[], input_type=list]
    clarification_history.1.required_information
      Input should be a valid string [..., input_value=['useful_life_years'],
                                      input_type=list]

and the outer catch-all in ``agent.execute`` rendered it as the generic
*\"An unexpected error occurred. Please try again.\"*  Nothing was recorded.

Cause: commit ``2acf43f`` started returning ``required_information`` — a
LIST holding the fields a round asked, in rendered order, so a typed
numbered answer can be field-tagged positionally (see
``get_clarification_history``) — while ``AgentContext`` still declared
``clarification_history: List[Dict[str, str]]``.  Production rows carry BOTH
shapes: ``[]`` (rows copied by ``seed_clarification_history``, which always
stores an empty list) and ``['useful_life_years']`` (a fresh round).
"""

from app.models.schemas import AgentContext

# Exactly the two entries that failed validation in production.
PROD_HISTORY = [
    {
        "question": "What is this purchase for?",
        "answer": "CAPITALIZE",
        "required_information": [],
    },
    {
        "question": "Useful life, depreciation method, salvage value?",
        "answer": "1) 5 2) STRAIGHT_LINE 3) 0",
        "required_information": ["useful_life_years"],
    },
]


def _ctx(history):
    """The minimal AgentContext the approved-plan fast path builds."""
    return AgentContext(
        organization={},
        user={"user_id": "00000000-0000-0000-0000-000000000001"},
        clarification_history=history,
    )


class TestAgentContextAcceptsRealClarificationHistory:
    def test_production_history_from_live_failure_validates(self):
        """The exact rows that raised ValidationError must now construct."""
        ctx = _ctx(PROD_HISTORY)
        assert ctx.clarification_history == PROD_HISTORY
        # Round-tripping keeps the field tags intact for positional routing.
        dumped = ctx.model_dump()
        assert dumped["clarification_history"][1]["required_information"] == [
            "useful_life_years"
        ]

    def test_legacy_entries_with_string_field_tags_still_validate(self):
        """Older rows / callers passed a bare string — never reject them."""
        history = [
            {"question": "Cash or credit?", "answer": "cash",
             "required_information": "payment method"},
            {"question": "Item nature?", "answer": "a"},  # key absent
            {"question": "Plain pair", "answer": "42"},   # legacy Dict[str, str]
        ]
        ctx = _ctx(history)
        assert ctx.clarification_history == history

    def test_default_history_is_empty_not_none(self):
        assert _ctx([]).clarification_history == []
