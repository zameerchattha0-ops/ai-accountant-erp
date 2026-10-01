"""
ERP AI Agent — Fixed-Format Questionnaire Contract
=====================================================================
ONE place where clarification questions are DEFINED, FORMATTED and
VALIDATED, so that:

* every consumer (the chat card, a wizard, an integration, a test) gets
  the SAME machine-readable shape — :func:`questionnaire_schema`;
* the question TEXT is rendered by code from a fixed template
  ("intro\\n1. …\\n2. …") — never hand-assembled per call site;
* an LLM may PHRASE the questions (warmer, context-aware wording), but it
  can never change WHICH fields are asked, may never ask about a fact that
  is already known, and its output is rejected wholesale on any schema
  violation — the deterministic bank stands.

Contract (``to_payload()`` / :func:`questionnaire_schema`)::

    {
      "version": 1,
      "intent": "register_fixed_asset",
      "intro": "To record this transaction I need a few things:",
      "questions": [
        {
          "id": "q1",
          "field": "useful_life_years",
          "kind": "number",              # choice|date|money|number|text
          "question": "…one sentence…",
          "options": [{"value": "...", "label": "..."}],  # choice only
          "answer_hint": "…how to answer…",
          "why": "…why it is needed…",
          "required": true
        }
      ]
    }

The NUMBERED TEXT form keeps the historical answer-merge contract: the
planner pairs each "N. question" line with the user's Nth answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

log = structlog.get_logger(__name__)

SCHEMA_VERSION = 1
QUESTIONNAIRE_INTRO = "To record this transaction I need a few things:"

KIND_CHOICE = "choice"
KIND_DATE = "date"
KIND_MONEY = "money"
KIND_NUMBER = "number"
KIND_TEXT = "text"
_KINDS = frozenset({KIND_CHOICE, KIND_DATE, KIND_MONEY, KIND_NUMBER, KIND_TEXT})

_MARKDOWN_RE = re.compile(r"\*\*|`|^\s{0,3}#{1,6}\s+", re.MULTILINE)
_QUESTION_MAX = 320
_OPTION_MAX = 60
_MAX_OPTIONS = 6

# The standardized date question (exact shape per the date protocol).
DATE_QUESTION = (
    "What is the transaction date? Reply TODAY, or the date as "
    "YYYY-MM-DD or DD/MM/YYYY (for example 2026-09-04 or 04/09/2026)."
)
_DATE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("TODAY", "Today"), ("YESTERDAY", "Yesterday"),
)


@dataclass(frozen=True)
class QuestionSpec:
    """One clarification question: field, kind, text, finite options."""

    field: str
    kind: str
    question: str
    options: Tuple[Tuple[str, str], ...] = ()  # (value, label) pairs
    answer_hint: Optional[str] = None
    why: Optional[str] = None


# ---------------------------------------------------------------------------
# THE QUESTION BANK — deterministic defaults for every askable field.
# The planner/reasoning layers use these texts (contracts preserved), the
# LLM may rephrase them, and this bank is always the fallback.
# ---------------------------------------------------------------------------
QUESTION_BANK: Dict[str, QuestionSpec] = {
    "transaction_nature": QuestionSpec(
        field="transaction_nature",
        kind=KIND_CHOICE,
        question=(
            "Is this item: (a) a FIXED ASSET (long-term use, to be capitalised), "
            "(b) an INVENTORY-STOCKED PRODUCT (resale stock — catalog flag only, "
            "quantities are not tracked), (c) a CONSUMABLE / one-off EXPENSE "
            "(expensed immediately), or (d) a SERVICE? Please answer with a, b, c or d."
        ),
        options=(
            ("FIXED_ASSET", "Fixed asset"),
            ("INVENTORY", "Inventory (resale stock)"),
            ("CONSUMABLE", "Consumable / expense"),
            ("SERVICE", "Service"),
        ),
        answer_hint="a, b, c or d",
        why="The nature decides the ledger and whether it depreciates.",
    ),
    "amount": QuestionSpec(
        field="amount", kind=KIND_MONEY,
        question="What is the transaction amount?",
        answer_hint="A number, e.g. 150000",
        why="Every journal line carries a value.",
    ),
    "transaction_date": QuestionSpec(
        field="transaction_date", kind=KIND_DATE, question=DATE_QUESTION,
        options=_DATE_OPTIONS, answer_hint="TODAY, YYYY-MM-DD or DD/MM/YYYY",
        why="Posting date — an entry without a date cannot be posted.",
    ),
    "payment_type": QuestionSpec(
        field="payment_type", kind=KIND_CHOICE,
        question="Was this paid in cash or on credit?",
        options=(("CASH", "Cash"), ("CREDIT", "On credit")),
        answer_hint="cash or credit",
        why="Cash settles immediately; credit opens a payable.",
    ),
    "supplier_name": QuestionSpec(
        field="supplier_name", kind=KIND_TEXT,
        question=(
            "Who is the supplier? If this is a one-off purchase from a local "
            "vendor, reply LOCAL VENDOR and it will be recorded against a "
            "'Local Vendor' account (created automatically if it does not "
            "exist yet)."
        ),
        answer_hint="Supplier name, or LOCAL VENDOR",
        why="A credit purchase needs the party ledger it owes.",
    ),
    "customer_name": QuestionSpec(
        field="customer_name", kind=KIND_TEXT,
        question="Who is the customer?",
        answer_hint="Customer name", why="The receivable belongs to a party.",
    ),
    "item_description": QuestionSpec(
        field="item_description", kind=KIND_TEXT,
        question=(
            "What item or service is being invoiced? (description for the "
            "invoice line — e.g. 'Web development services', 'HP laptops')"
        ),
        answer_hint="Item or service description",
        why="The document line needs a description.",
    ),
    "quantity": QuestionSpec(
        field="quantity", kind=KIND_NUMBER,
        question=(
            "How many units are you invoicing? (quantity — reply with just "
            "the number; the line total you gave is divided across the units)"
        ),
        answer_hint="A number", why="Unit price is derived from the total.",
    ),
    "asset_name": QuestionSpec(
        field="asset_name", kind=KIND_TEXT,
        question="Which asset is this about (asset name or code)?",
        answer_hint="Asset name or code",
        why="Depreciation and disposal act on ONE registered asset.",
    ),
    # --- Fixed-asset lifecycle: the acquisition questionnaire -------------
    "useful_life_years": QuestionSpec(
        field="useful_life_years", kind=KIND_NUMBER,
        question=(
            "What is the USEFUL LIFE of this asset in years? (e.g. vehicles 5, "
            "computers 4, furniture 10 — reply NONE if you do not want a "
            "depreciation schedule yet)"
        ),
        options=(("NONE", "No depreciation schedule"),),
        answer_hint="Number of years, or NONE",
        why="Depreciation charge = (cost − salvage) ÷ useful life.",
    ),
    "depreciation_method": QuestionSpec(
        field="depreciation_method", kind=KIND_CHOICE,
        question=(
            "Which DEPRECIATION METHOD should I use? (a) STRAIGHT LINE "
            "(equal charge every month), (b) REDUCING BALANCE (a fixed % of "
            "the book value each year — reply the % too if you have one), or "
            "(c) NONE for now"
        ),
        options=(
            ("STRAIGHT_LINE", "Straight line"),
            ("REDUCING_BALANCE", "Reducing balance"),
            ("NONE", "None for now"),
        ),
        answer_hint="straight line / reducing balance / none",
        why="The method decides how the asset is written down each period.",
    ),
    "salvage_value": QuestionSpec(
        field="salvage_value", kind=KIND_MONEY,
        question=(
            "What RESIDUAL / SALVAGE value will this asset have at the end of "
            "its useful life? (reply 0 if none — depreciation never takes the "
            "book value below this)"
        ),
        answer_hint="A number, e.g. 50000 — or 0",
        why="Depreciation stops at the salvage value.",
    ),
    # --- Projects --------------------------------------------------------
    "project_name": QuestionSpec(
        field="project_name", kind=KIND_TEXT,
        question="What is the project called?",
        answer_hint="Project name, e.g. 'Mobile App'",
        why="The project record is identified by its name.",
    ),
    "project_code": QuestionSpec(
        field="project_code", kind=KIND_TEXT,
        question=(
            "Which project code should I use? (a short code, e.g. MOB-001 — "
            "reply NONE and I will generate one)"
        ),
        options=(("NONE", "Generate one for me"),),
        answer_hint="A short code, or NONE",
        why="The project ledger is keyed by its code.",
    ),
}


def _generic_spec(field_name: str) -> QuestionSpec:
    label = field_name.replace("_", " ")
    return QuestionSpec(
        field=field_name, kind=KIND_TEXT,
        question=f"Please provide the {label}.",
    )


def spec_for(field_name: str) -> QuestionSpec:
    """The bank spec for *field_name* (generic fallback — never None)."""
    return QUESTION_BANK.get(field_name) or _generic_spec(field_name)


def questionnaire_schema() -> Dict[str, Any]:
    """The fixed JSON schema, embeddable by ANY consumer."""
    return {
        "version": SCHEMA_VERSION,
        "type": "object",
        "required": ["version", "intent", "intro", "questions"],
        "properties": {
            "version": {"type": "integer", "const": SCHEMA_VERSION},
            "intent": {"type": "string"},
            "intro": {"type": "string"},
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "field", "kind", "question", "required"],
                    "properties": {
                        "id": {"type": "string"},
                        "field": {"type": "string"},
                        "kind": {"enum": sorted(_KINDS)},
                        "question": {"type": "string", "maxLength": _QUESTION_MAX},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["value", "label"],
                                "properties": {
                                    "value": {"type": "string"},
                                    "label": {"type": "string"},
                                },
                            },
                        },
                        "answer_hint": {"type": ["string", "null"]},
                        "why": {"type": ["string", "null"]},
                        "required": {"type": "boolean"},
                    },
                },
            },
            "filled": {
                "type": "object",
                "description": (
                    "SKIP-AND-FILL facts (Python-validated): field -> value "
                    "answers the model confirmed from the request/context. "
                    "Filled fields are NOT asked."
                ),
            },
        },
    }


@dataclass
class Questionnaire:
    """A concrete, renderable questionnaire."""

    intent: str = ""
    intro: str = QUESTIONNAIRE_INTRO
    questions: List[QuestionSpec] = dc_field(default_factory=list)
    source: str = "deterministic"  # deterministic | llm_assisted
    # SKIP-AND-FILL: facts the questionnaire model confirmed from the
    # provided facts/context (Python-validated).  The field is NOT asked
    # and is recorded as answered history, so no later round re-asks it.
    filled_facts: Dict[str, str] = dc_field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.questions

    def fields(self) -> List[str]:
        return [q.field for q in self.questions]

    def render_text(self) -> Optional[str]:
        """The numbered text form (historical answer-merge contract)."""
        cleaned = [q for q in self.questions if (q.question or "").strip()]
        if not cleaned:
            return None
        if len(cleaned) == 1:
            return cleaned[0].question
        lines = [self.intro or QUESTIONNAIRE_INTRO]
        for i, q in enumerate(cleaned, start=1):
            lines.append(f"{i}. {q.question}")
        return "\n".join(lines)

    def render_options(self) -> Optional[List[Optional[List[Dict[str, str]]]]]:
        """Backend tap-to-answer payload, INDEX-ALIGNED with the text."""
        payload: List[Optional[List[Dict[str, str]]]] = []
        any_options = False
        for q in self.questions:
            if q.options:
                payload.append([{"value": v, "label": lbl} for v, lbl in q.options])
                any_options = True
            else:
                payload.append(None)
        return payload if any_options else None

    def to_payload(self) -> Dict[str, Any]:
        """The fixed-format payload (see :func:`questionnaire_schema`)."""
        payload: Dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "intent": self.intent,
            "intro": self.intro or QUESTIONNAIRE_INTRO,
            "source": self.source,
            "questions": [
                {
                    "id": f"q{i}",
                    "field": q.field,
                    "kind": q.kind if q.kind in _KINDS else KIND_TEXT,
                    "question": q.question,
                    "options": [{"value": v, "label": lbl} for v, lbl in q.options]
                    or None,
                    "answer_hint": q.answer_hint,
                    "why": q.why,
                    "required": True,
                }
                for i, q in enumerate(self.questions, start=1)
            ],
        }
        if self.filled_facts:
            payload["filled"] = dict(self.filled_facts)
        return payload


def _known(value: Any) -> bool:
    """True when an entity counts as ANSWERED (never ask it again)."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def build_questionnaire(
    missing_fields: Sequence[str],
    questions: Sequence[str] = (),
    entities: Optional[Dict[str, Any]] = None,
    intent: str = "",
) -> Questionnaire:
    """Deterministic questionnaire from the planner's own gap list.

    * pairs each missing field with the planner's question text (falling
      back to the bank, then to a generic "please provide …");
    * DROPS any field already answered in *entities* — a question about a
      known fact can never be built here;
    * de-duplicates fields while preserving the planner's order.
    """
    ents = entities or {}
    q_by_field: Dict[str, str] = {}
    for f, q in zip(list(missing_fields), list(questions)):
        q_by_field[str(f)] = str(q)
    ordered: List[str] = []
    for f in list(missing_fields) + [k for k in q_by_field if k not in missing_fields]:
        name = str(f or "").strip()
        if name and name not in ordered:
            ordered.append(name)

    specs: List[QuestionSpec] = []
    for name in ordered:
        if _known(ents.get(name)):
            continue
        base = spec_for(name)
        provided = q_by_field.get(name)
        if provided and provided.strip():
            specs.append(
                QuestionSpec(
                    field=name, kind=base.kind, question=provided.strip(),
                    options=base.options, answer_hint=base.answer_hint,
                    why=base.why,
                )
            )
        else:
            specs.append(base)
    return Questionnaire(intent=intent, questions=specs)


def single_question_payload(
    field_name: str,
    question: str,
    options: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Fixed-format payload for a ONE-question clarification (any site)."""
    base = spec_for(field_name)
    spec = QuestionSpec(
        field=field_name,
        kind=base.kind,
        question=question,
        options=tuple((o, o) for o in options or ()) or base.options,
        answer_hint=base.answer_hint,
        why=base.why,
    )
    return Questionnaire(intent="", questions=[spec]).to_payload()


# ---------------------------------------------------------------------------
# LLM phrasing — FIXED schema in, VALIDATED schema out, deterministic bank
# as the floor.  The model may reword; it may never widen the question set,
# change a field, or ask about a known fact.
# ---------------------------------------------------------------------------
QUESTIONNAIRE_LLM_INSTRUCTIONS = """You write the clarification questionnaire of an accounting agent.

You are given:
  * INTENT — what the user is trying to record;
  * MUST_ASK — the fields that are genuinely missing (each with a draft question);
  * KNOWN_FACTS — facts extracted from the user's own words (NEVER ask these);
  * CONTEXT — what the books already contain for this request.

Reply with ONLY this JSON object (no prose, no markdown):

{"intro": "one short sentence",
 "questions": [{"field": "<one MUST_ASK field, verbatim>",
                "kind": "choice|date|money|number|text",
                "question": "<ONE sentence, at most 300 characters>",
                "options": [{"value": "<tapped answer>", "label": "<chip text>"}],
                "answer_hint": "<how to answer>",
                "why": "<why it is needed>"},
               {"field": "<another MUST_ASK field, verbatim>",
                "already_answered": true,
                "value": "<the fact, copied from KNOWN_FACTS or CONTEXT>"}]}

A MUST_ASK field whose answer ALREADY EXISTS in KNOWN_FACTS or CONTEXT
(extraction simply missed it) is NOT asked — replace its question with the
"already_answered" form above.  Python validates the value (a choice must
be one of the draft's own option values, a date must parse, a money/number
must be numeric) and then treats the field as ANSWERED.  An invalid fill
is DISCARDED and the question is asked instead.

Rules (any violation discards your answer):
  1. One entry per MUST_ASK field — never invent fields; entries are
     questions OR already_answered fills, never both for the same field;
  2. NEVER ask about anything in KNOWN_FACTS or CONTEXT — skip-and-fill it;
  3. Keep the draft's meaning and number formats; you may only reword for
     clarity, and you must repeat the known facts the question relies on;
  4. For a finite decision set give 2-6 tap options; otherwise options [].
  5. No markdown, no numbering, no lists inside a question.
"""


def _clean_text(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    text = _MARKDOWN_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > limit:
        return None
    return text


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = str(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_llm_question(
    entry: Any, allowed: Dict[str, QuestionSpec]
) -> Optional[Tuple[str, QuestionSpec]]:
    """(field, QuestionSpec) for a valid LLM entry, else ``None``."""
    if not isinstance(entry, dict):
        return None
    field_name = str(entry.get("field") or "").strip()
    if field_name not in allowed:  # unknown field -> rejected
        return None
    question = _clean_text(entry.get("question"), _QUESTION_MAX)
    if not question:
        return None
    base = allowed[field_name]
    kind = str(entry.get("kind") or base.kind).strip().lower()
    if kind not in _KINDS:
        kind = base.kind
    options: List[Tuple[str, str]] = []
    raw_options = entry.get("options")
    if isinstance(raw_options, list):
        for opt in raw_options[:_MAX_OPTIONS]:
            if not isinstance(opt, dict):
                continue
            value = _clean_text(opt.get("value"), _OPTION_MAX)
            label = _clean_text(opt.get("label"), _OPTION_MAX) or value
            if value and label:
                options.append((value, label))
    if len(options) == 1:
        options = []  # a single tap option is not a choice
    if not options:
        options = list(base.options)  # deterministic options win back
    if kind == KIND_CHOICE and not options:
        kind = KIND_TEXT
    return (
        field_name,
        QuestionSpec(
            field=field_name,
            kind=kind,
            question=question,
            options=tuple(options),
            answer_hint=_clean_text(entry.get("answer_hint"), 120)
            or base.answer_hint,
            why=_clean_text(entry.get("why"), 160) or base.why,
        ),
    )


def _norm_token(value: Any) -> str:
    """Separator-insensitive token form ("FIXED_ASSET" == "fixed asset")."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _validate_llm_fill(
    entry: Any, allowed: Dict[str, QuestionSpec]
) -> Optional[Tuple[str, str]]:
    """(field, validated value) for a SKIP-AND-FILL entry, else ``None``.

    The questionnaire model may claim a MUST_ASK field is already answered
    ONLY when the supplied value survives Python's own validation for the
    field's kind:

      * a DATE must parse mechanically (relative words like "yesterday"
        are resolved to ISO — never trusted verbatim);
      * a CHOICE must be one of the field's OWN option values (the model
        has no fact vocabulary of its own);
      * a MONEY / NUMBER must be numeric; a TEXT must be clean.

    A rejected fill changes nothing: the deterministic question stays in
    the round — the gap floor never loses a genuinely open question.
    """
    if not isinstance(entry, dict):
        return None
    field_name = str(entry.get("field") or "").strip()
    if field_name not in allowed or not entry.get("already_answered"):
        return None
    spec = allowed[field_name]
    raw_value = entry.get("value")
    if raw_value in (None, "", [], {}):
        return None
    if spec.kind == KIND_DATE:
        from app.date_parser import parse_transaction_date

        parsed = parse_transaction_date(str(raw_value))
        if getattr(parsed, "ok", False) and getattr(parsed, "iso_date", None):
            return field_name, str(parsed.iso_date)
        return None
    if spec.options:
        wanted = _norm_token(raw_value)
        for value, _label in spec.options:
            if _norm_token(value) == wanted:
                return field_name, value
        return None
    if spec.kind in (KIND_MONEY, KIND_NUMBER):
        try:
            number = float(str(raw_value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return field_name, str(number)
    text = _clean_text(raw_value, 120)
    if not text:
        return None
    return field_name, text


def _phrasing_prompt(
    base: Questionnaire,
    entities: Dict[str, Any],
    context_summary: Optional[Dict[str, Any]],
) -> str:
    must_ask = [
        {
            "field": q.field,
            "draft": q.question,
            "kind": q.kind,
            "options": [{"value": v, "label": lbl} for v, lbl in q.options],
        }
        for q in base.questions
    ]
    payload = {
        "INTENT": base.intent,
        "MUST_ASK": must_ask,
        "KNOWN_FACTS": {k: v for k, v in (entities or {}).items() if _known(v)},
        "CONTEXT": context_summary or {},
    }
    return (
        f"{QUESTIONNAIRE_LLM_INSTRUCTIONS}\n\n"
        f"INPUT:\n{json.dumps(payload, default=str, ensure_ascii=False)}"
    )


async def build_questionnaire_with_llm(
    *,
    missing_fields: Sequence[str],
    questions: Sequence[str] = (),
    entities: Optional[Dict[str, Any]] = None,
    intent: str = "",
    client: Any = None,
    context_summary: Optional[Dict[str, Any]] = None,
    enabled: bool = True,
) -> Questionnaire:
    """The deterministic questionnaire, optionally re-phrased by the LLM.

    The LLM output is validated against the fixed schema and the ALLOWED
    field set; a violation falls back to the deterministic text for that
    question, and a total failure keeps the whole deterministic version.
    Provider exceptions are swallowed (a questionnaire must never fail a
    turn) — a programming error (AssertionError) is NOT.
    """
    base = build_questionnaire(missing_fields, questions, entities, intent)
    if base.is_empty() or not enabled or client is None:
        return base

    allowed: Dict[str, QuestionSpec] = {q.field: q for q in base.questions}
    prompt = _phrasing_prompt(base, entities or {}, context_summary)
    try:
        raw = await client.generate_text_light(prompt)
    except AssertionError:  # test guards must stay loud
        raise
    except Exception as exc:  # noqa: BLE001 — phrasing is best-effort
        log.info("questionnaire.llm_unavailable", error=str(exc)[:200])
        return base

    payload = _extract_json(str(raw or ""))
    if not payload:
        log.info("questionnaire.llm_rejected", reason="unparseable")
        return base

    ordered: List[QuestionSpec] = []
    seen: set = set()
    fills: Dict[str, str] = {}
    for entry in payload.get("questions") or []:
        # SKIP-AND-FILL: the model may mark a MUST_ASK field answered when
        # the fact exists in KNOWN_FACTS/CONTEXT — Python validates the
        # value (choice vocabulary / date parse / numeric) and the field
        # stops being asked.
        if isinstance(entry, dict) and entry.get("already_answered"):
            filled = _validate_llm_fill(entry, allowed)
            if filled and filled[0] not in seen:
                fills[filled[0]] = filled[1]
            continue
        validated = _validate_llm_question(entry, allowed)
        if not validated:
            continue
        field_name, spec = validated
        if field_name in seen:
            continue
        seen.add(field_name)
        ordered.append(spec)
    # A validated fill never empties the round: the plan was built WITHOUT
    # these facts, so at least ONE question survives (the highest-priority
    # gap) — the answer round is what re-plans with the filled facts.
    if fills and not ordered and base.questions:
        survivor = base.questions[0]
        fills.pop(survivor.field, None)
        seen.add(survivor.field)
        ordered.append(survivor)
    # Every remaining field is still asked: fill the gaps deterministically.
    for question in base.questions:
        if question.field not in seen and question.field not in fills:
            ordered.append(question)

    intro = _clean_text(payload.get("intro"), 160) or base.intro
    log.info(
        "questionnaire.llm_used",
        fields=[q.field for q in ordered],
        filled=list(fills),
        rephrased=len(seen),
    )
    return Questionnaire(
        intent=intent,
        intro=intro,
        questions=ordered,
        source="llm_assisted",
        filled_facts=fills,
    )








# ---------------------------------------------------------------------------
# AUTHORED QUESTIONNAIRE — the reasoning LLM writes the questions itself,
# inside the fixed schema.  Validation is the contract: only known ERP
# field names, only unanswered facts, sane options — everything else is
# dropped and the deterministic bank stands.
# ---------------------------------------------------------------------------
# Every field an authored question may target (bank + planner vocabulary).
# The field is what routes the answer back into entities — a question with
# an unknown field could never be answered into the books, so it is
# rejected outright.
AUTHORED_FIELDS: frozenset = frozenset(
    set(QUESTION_BANK)
    | {
        "transaction_purpose",
        "capitalization_decision",
        "settlement_position",
        "payment_method",
        "description",
        "asset_code",
        "supplier_name",
        "customer_name",
        "account_name",
        "revenue_account_name",
        "date_from",
        "date_to",
        "project_name",
        "disposal_type",
        "proceeds_amount",
        "depreciation_amount",
        "period",
        "note",
    }
)


def validate_authored_questions(
    entries: Any, known: Optional[Dict[str, Any]] = None
) -> List[QuestionSpec]:
    """Validate an LLM-authored ``questions[]`` against the fixed schema.

    Rejections (never repaired): unknown field, empty/oversized text,
    markdown, or a field already answered in *known*.  Options are
    normalised; a choice question with no usable options falls back to
    free text rather than inventing choices.
    """
    if not isinstance(entries, list):
        return []
    ents = known or {}
    allowed = {name: spec_for(name) for name in AUTHORED_FIELDS}
    out: List[QuestionSpec] = []
    seen: set = set()
    for entry in entries[:12]:
        if not isinstance(entry, dict):
            continue
        field_name = str(entry.get("field") or "").strip()
        if field_name not in allowed or field_name in seen:
            continue
        if _known(ents.get(field_name)):
            continue  # never ask what the user already stated
        question = _clean_text(entry.get("question"), _QUESTION_MAX)
        if not question:
            continue
        base = allowed[field_name]
        validated = _validate_llm_question(
            {**entry, "field": field_name, "question": question},
            {field_name: base},
        )
        if not validated:
            continue
        seen.add(field_name)
        out.append(validated[1])
    return out


def questionnaire_from_authored(
    payload: Any,
    intent: str = "",
    known: Optional[Dict[str, Any]] = None,
) -> Optional[Questionnaire]:
    """A questionnaire from an LLM-authored payload, or ``None``.

    Accepts the reasoning layer's ``question`` object:
    ``{"text": …, "questions": [{field, kind, question, options, why}],
       "options_per_part": [[…]]}``.  The structured ``questions[]`` wins;
    when it is absent (older model output) the numbered ``text`` plus
    ``options_per_part`` is converted so every consumer sees ONE shape.
    """
    if not isinstance(payload, dict):
        return None

    specs = validate_authored_questions(payload.get("questions"), known)
    if specs:
        intro = ""
        text = str(payload.get("text") or "").strip()
        # Keep the model's intro line when it is not itself a question.
        first_line = text.splitlines()[0].strip() if text else ""
        if first_line and not re.match(r"^\d+[.)]\s", first_line):
            intro = first_line[:200]
        return Questionnaire(
            intent=intent, intro=intro or QUESTIONNAIRE_INTRO,
            questions=specs, source="reasoning_llm",
        )

    # Back-compat: numbered text + aligned tap options, no field names.
    text = str(payload.get("text") or "").strip()
    if not text:
        return None
    numbered = re.findall(r"^\s*\d+[.)]\s*(.+)$", text, re.MULTILINE)
    intro = "" if numbered else text
    statements = numbered or [text]
    parts = payload.get("options_per_part")
    specs_fallback: List[QuestionSpec] = []
    for index, statement in enumerate(statements):
        question = _clean_text(statement, _QUESTION_MAX)
        if not question:
            continue
        options: List[Tuple[str, str]] = []
        if isinstance(parts, list) and index < len(parts):
            part = parts[index]
            if isinstance(part, list):
                for raw in part[:6]:
                    value = _clean_text(raw, _OPTION_MAX)
                    if value:
                        options.append((value, value))
        specs_fallback.append(
            QuestionSpec(
                field=f"unstructured_{index + 1}",
                kind=KIND_CHOICE if options else KIND_TEXT,
                question=question,
                options=tuple(options),
            )
        )
    if not specs_fallback:
        return None
    return Questionnaire(
        intent=intent, intro=intro or QUESTIONNAIRE_INTRO,
        questions=specs_fallback, source="reasoning_llm_unstructured",
    )


# ---------------------------------------------------------------------------
# AUTHORED-BY-REQUEST QUESTIONNAIRE — the provider call that REPLACES the
# template as the author of user-visible questions.  Whenever the plan still
# has material gaps, the same Token Harbor model that reasons about the
# request is given the request + facts + answered history and WRITES the
# questionnaire itself, in the fixed JSON format the frontend renders.
# Python validates only (answer-routing field vocabulary, known facts never
# asked, option/kind/text shape) — the deterministic bank authors NOTHING on
# this path; it stands as the provider-down floor.
# ---------------------------------------------------------------------------

# One-line gloss per routing field: guidance for the question WRITER (what
# an answer to this field means in the books), never a question template.
_FIELD_GLOSS: Dict[str, str] = {
    "transaction_date": "when the event happened — a date",
    "payment_type": "how it was settled — cash ledger, bank ledger, or on credit",
    "payment_method": "the recorded settlement (CASH, BANK, CREDIT, ...)",
    "transaction_nature": (
        "what the item actually is — fixed asset, inventory-stocked product, "
        "consumable/one-off expense, or service"
    ),
    "transaction_purpose": "what the money was actually for (rent, salaries, repairs, ...)",
    "capitalization_decision": "capitalise the cost or expense it immediately",
    "settlement_position": "paid now, still outstanding, or prepaid",
    "amount": "the money amount",
    "supplier_name": "which supplier",
    "customer_name": "which customer",
    "item_description": "what the item/product/service is",
    "quantity": "how many units",
    "asset_name": "the asset's name/identification",
    "useful_life_years": "how many years the asset will be used",
    "depreciation_method": "straight line or reducing balance",
    "salvage_value": "the residual value at the end of the asset's life",
    "account_name": "which ledger account to post to",
    "disposal_type": "sold, scrapped, or written off",
    "proceeds_amount": "the money received on a disposal",
    "period": "the accounting period the entry belongs to",
    "note": "any further detail the user wants recorded",
}

_AUTHORED_QUESTIONNAIRE_PROMPT = """You are the clarification writer of an accounting agent (assisted ERP).

A request could not be posted yet because material facts are missing.  You
analyse the user's request, the facts already extracted and the answers
already given, then WRITE the questions that close the remaining gaps — in
the product's fixed JSON format (the frontend renders it directly, and each
"field" routes the answer back into the books).

You are given:
  * USER_REQUEST — the user's own words;
  * INTENT — the operation the system will record;
  * MISSING_MATERIAL_FACTS — the facts that currently block a correct posting;
  * KNOWN_FACTS — already extracted from the user's own words (NEVER ask);
  * ANSWERED_HISTORY — Q/A from earlier rounds (NEVER re-ask);
  * FIELD_VOCABULARY — the ONLY field names an answer may route to.

Reply with ONLY this JSON object (no prose, no markdown):

{"intro": "<one short sentence>",
 "questions": [{"field": "<one FIELD_VOCABULARY name>",
                "kind": "choice|date|money|number|text",
                "question": "<ONE sentence, at most 300 characters>",
                "options": [{"value": "<the recorded answer>", "label": "<chip text>"}],
                "answer_hint": "<how to answer>",
                "why": "<why it is needed>"}]}

Rules (any violation discards that question):
  1. Ask EVERY missing material fact in this ONE questionnaire — never
     invent fields and never ask anything in KNOWN_FACTS or ANSWERED_HISTORY;
  2. A finite decision gets 2-6 options: "value" is what the answer records
     ("CASH"), "label" is the chip text ("Cash"); otherwise "options": [];
  3. One sentence per question, plain text — no markdown, no numbering; repeat
     the known facts the question relies on so it needs no outside context;
  4. "field" is what routes the answer into the books — a question whose field
     is not in FIELD_VOCABULARY is dropped;
  5. TODAY (when given) resolves relative wording — never ask for what it
     already resolves.
"""


def _authored_questionnaire_prompt(
    *,
    user_request: str,
    intent: str,
    missing_fields: Sequence[str],
    entities: Optional[Dict[str, Any]] = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
    today: str = "",
) -> str:
    """Assemble the authoring prompt (request + facts + vocabulary)."""
    vocabulary = []
    for name in sorted(AUTHORED_FIELDS):
        gloss = _FIELD_GLOSS.get(name)
        vocabulary.append(f"  - {name}: {gloss}" if gloss else f"  - {name}")
    payload: Dict[str, Any] = {
        "USER_REQUEST": user_request,
        "INTENT": intent,
        "MISSING_MATERIAL_FACTS": list(missing_fields),
        "KNOWN_FACTS": {k: v for k, v in (entities or {}).items() if _known(v)},
        "ANSWERED_HISTORY": list(history or []),
        "TODAY": today,
    }
    return (
        f"{_AUTHORED_QUESTIONNAIRE_PROMPT}\n"
        "FIELD_VOCABULARY (the only allowed field names):\n"
        + "\n".join(vocabulary)
        + f"\n\nINPUT:\n{json.dumps(payload, default=str, ensure_ascii=False)}"
    )


async def author_questionnaire(
    *,
    client: Any = None,
    user_request: str = "",
    intent: str = "",
    missing_fields: Sequence[str] = (),
    entities: Optional[Dict[str, Any]] = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
    today: str = "",
) -> Optional[Questionnaire]:
    """The provider WRITES the questionnaire for the open material gaps.

    Returns ``None`` (the caller then uses the deterministic floor) when the
    provider is absent/failed, the answer is unparseable, or no authored
    question survived validation — a material gap is never silently dropped,
    but no template text is shown while the model answered.
    """
    if client is None or not list(missing_fields or ()):
        return None
    prompt = _authored_questionnaire_prompt(
        user_request=user_request,
        intent=intent,
        missing_fields=missing_fields,
        entities=entities,
        history=history,
        today=today,
    )
    try:
        raw = await client.generate_text_light(prompt)
    except AssertionError:  # test guards must stay loud
        raise
    except Exception as exc:  # noqa: BLE001 — authoring is best-effort
        log.info("questionnaire.author_unavailable", error=str(exc)[:200])
        return None
    payload = _extract_json(str(raw or ""))
    if not payload:
        log.info("questionnaire.author_rejected", reason="unparseable")
        return None
    specs = validate_authored_questions(payload.get("questions"), entities or {})
    if not specs:
        log.info("questionnaire.author_rejected", reason="no_valid_question")
        return None
    intro = _clean_text(payload.get("intro"), 200) or QUESTIONNAIRE_INTRO
    log.info("questionnaire.authored", fields=[q.field for q in specs])
    return Questionnaire(
        intent=intent,
        intro=intro,
        questions=specs,
        source="llm_authored",
    )

