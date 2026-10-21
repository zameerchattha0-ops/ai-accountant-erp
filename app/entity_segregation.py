"""
AI-first perception stage â€” grounded LLM fact extraction.

ARCHITECTURE CHANGE (S1 -> S2)
------------------------------
S1 was a *gap-filler*: keyword regex ran first, and the LLM was consulted only
when the regex came up empty. That made the pipeline keyword-oriented â€” any
phrasing outside the hard-coded templates produced a questionnaire asking for
facts the user had already given (e.g. "record a sale of two chairs on credit
for 23000 to hjk pvt limited" asked "Who is the customer?").

S2 inverts it, AI-first:
  1. The user's request goes to the LLM FIRST, together with a distilled
     rulebook of the deterministic agent (grounding, written numbers, date
     resolution, the nature taxonomy, party direction).
  2. The extracted facts are GROUNDED in Python: every copied value must
     occur verbatim in the user's own text; numbers must be traceable to a
     digit or written-number token; dates must be an ISO/slash date in the
     text or a resolvable relative word; payment methods must map to a
     keyword that is actually present.
  3. The grounded facts prefill the deterministic planner, so the
     questionnaire contains ONLY genuinely missing fields and everything the
     user stated flows to the next stages.
  4. The regex extractor remains as the FALLBACK: provider down, timeout,
     malformed JSON -> {} -> exactly the old keyword behaviour. The LLM can
     never make a request fail.

This stage never mutates anything and never talks to tools; it is perception
only. The planner + trusted tools keep full authority over what is executed.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from typing import Any, Dict, Optional, Sequence

import structlog

log = structlog.get_logger(__name__)

# Generic nouns that must never be taken as an item description
# (mirrors the filter in planner._extract_item).  Pronouns are included
# because production 2026-10-14 saw "selling them 2 laptops" propose
# "them" as the item — a pronoun can never name a product.
_GENERIC_ITEMS = frozenset({
    "it", "something", "goods", "items", "stuff", "things", "product", "products",
    "them", "they", "these", "those", "this", "that", "which", "who", "whom",
})

# Canonical nature taxonomy â€” mirrors reasoning.py's nature question values.
_NATURES = frozenset({
    # purchase family
    "FIXED_ASSET", "INVENTORY", "OPERATING_EXPENSE", "SERVICE",
    # sale family
    "GOODS", "ASSET_DISPOSAL", "OTHER_INCOME",
    # expense family
    "PREPAID_EXPENSE", "OWNER_DRAWING",
    # settlement family (receipt / payment)
    "ALLOCATION", "ADVANCE", "LOAN_OR_SETTLEMENT",
    # return family
    "RETURN_OF_GOODS", "PRICE_ADJUSTMENT", "SERVICE_REVERSAL",
    # legacy planner vocabulary
    "CONSUMABLE", "REVENUE", "PREPAYMENT", "DEPOSIT_ADVANCE",
    "INTANGIBLE_ASSET",
})

# Payment-method grounding: canonical -> keyword(s) that must appear in text.
_PAYMENT_KEYWORDS = {
    "CASH": ("cash",),
    "CREDIT": ("credit", "khata", "udhaar", "udhar"),
    "BANK_TRANSFER": ("bank", "wire", "transfer", "online"),
    "CHEQUE": ("cheque", "check"),
    "CARD": ("card",),
}

# Written-number vocabulary for grounding quantities/amounts stated in words.
_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "pair": 2, "couple": 2, "dozen": 12,
    "hundred": 100, "thousand": 1000, "lac": 100000, "lakh": 100000,
}

# Relative date words the LLM may resolve using today's date.
_RELATIVE_DAYS = frozenset(
    {"today", "yesterday", "tomorrow", "tonight", "this morning"}
)

# Fields this stage may ever return.
_ALLOWED_FIELDS = frozenset(
    {
        "customer_name",
        "supplier_name",
        "item_description",
        "item_quantity",
        "amount",
        "payment_method",
        "transaction_date",
        "transaction_nature",
        # Expense purpose (record_expense's purpose-first ladder): WHAT THE
        # MONEY WAS FOR — mapped to the canonical purpose taxonomy and
        # keyword-grounded below, so a request that states its purpose
        # ("Paid for travelling") is never re-asked for it.
        "transaction_purpose",
        # Loan contract facts (record_loan): the FIRST hit reads the terms
        # the message already states, so the second-run questionnaire asks
        # only what is genuinely missing (never facts the user gave).
        "loan_direction",
        "counterparty",
        "narration",
        "first_payment_date",
        "tenure_months",
        "frequency",
    }
)

_NAME_FIELDS = frozenset({"customer_name", "supplier_name", "item_description"})

_SYSTEM_PROMPT = (
    "You are the perception stage of an accounting ERP agent. Read the "
    "user's request and extract every accounting fact it already states.\n"
    "HARD RULES:\n"
    "1. COPY text values VERBATIM from the request - same words, same "
    "order, same spelling. NEVER invent, translate, or rephrase a name.\n"
    "2. If a fact is not stated, OMIT its key entirely. NEVER guess.\n"
    "3. Numbers: convert written numbers to digits (two -> 2; 2.5 lac -> "
    "250000). amount is the money value without currency symbols. "
    "item_quantity is the count of units.\n"
    "4. transaction_date: resolve relative dates (today/yesterday/"
    "tomorrow) to ISO YYYY-MM-DD using the provided today's date. Format "
    "explicit dates as YYYY-MM-DD (DD/MM/YYYY is day-first).\n"
    "5. transaction_nature - classify ONLY when the request itself makes "
    "what this is unambiguous. When unsure, OMIT the key. The allowed "
    "values are listed below.\n"
    "6. payment_method: CASH, CREDIT, BANK_TRANSFER, CHEQUE or CARD.\n"
    "7. Direction: money coming in (sale, invoice, receipt) names a "
    "customer_name; money going out (purchase, bill, expense, payment) "
    "names a supplier_name. A borrowing, lending or repayment request "
    "names neither role - never force one.\n"
    "8. Loan facts - ONLY for a borrowing/lending request, and only what "
    "the request states (omit everything else): loan_direction "
    "(BORROWED when the business receives the money, GIVEN when it "
    "lends it - only when the wording says borrow/lend/give), "
    "counterparty (the lender or borrower name copied verbatim), "
    "narration (the facility label copied verbatim), first_payment_date "
    "(ISO YYYY-MM-DD), tenure_months (the number of months), "
    "frequency (MONTHLY, QUARTERLY, SEMI_ANNUAL, ANNUALLY or CUSTOM).\n"
    "9. item_description - the PRODUCT or SERVICE being sold, bought or "
    "invoiced (the noun after the count, e.g. 'selling them 2 laptops' -> "
    "'laptops'). It is NEVER a person or company name (that is "
    "customer_name/supplier_name) and NEVER a pronoun (it/them/this/that/"
    "these/those). When the request names no product or service, OMIT the "
    "key - never invent one.\n"
    "Answer with ONLY a JSON object."
)



def _norm(text) -> str:
    """Lowercase, punctuation-free, whitespace-collapsed form for grounding."""
    lowered = str(text or "").lower()
    lowered = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", lowered).strip()


def _is_grounded(candidate, normalized_message: str) -> bool:
    """True only when the candidate text occurs verbatim in the message."""
    value = _norm(candidate)
    if len(value) < 2:
        return False
    return value in normalized_message


def _clean_candidate(value) -> str:
    """Strip quoting/wrapping the model may add around a copied value."""
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    # A leading preposition is a copy artefact, not part of the name.
    text = re.sub(r"^(?:to|from|for|of|the)\s+", "", text, flags=re.IGNORECASE)
    return text.strip(" .;,:-")


def _parse_json_response(raw) -> dict:
    """Extract the first JSON object from the response, or {} on any failure."""
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}



def _evaluate_number_run(run) -> float:
    """Evaluate one run of written number words ("twenty three thousand" -> 23000).

    Standard English accumulator: additive words accumulate, "hundred"
    multiplies the current group, and thousand/lac/million multiply the whole
    group accumulated so far.
    """
    total = 0.0
    current = 0.0
    for word in run:
        num = _WORD_NUMBERS.get(word)
        if num is None:
            continue
        if num == 100:
            current = (current or 1) * 100
        elif num >= 1000:
            total += (current or 1) * num
            current = 0.0
        else:
            current += num
    return total + current


def _written_values_in(normalized: str) -> set:
    """Every value expressible by the number words present in the text.

    Hyphenated compounds are equivalent to their spaced form
    ("twenty-three" == "twenty three"), and consecutive number words are
    evaluated as one phrase so multiplicative forms such as
    "twenty-three thousand" are traceable.
    """
    words = re.findall(r"[a-z]+", re.sub(r"[-]", " ", normalized or ""))
    values: set = set()
    run: list = []
    for word in words:
        if word in _WORD_NUMBERS:
            run.append(word)
            continue
        if run:
            values.add(_evaluate_number_run(run))
            run = []
    if run:
        values.add(_evaluate_number_run(run))
    return {v for v in values if v > 0}


def _number_grounded(value: float, normalized: str) -> bool:
    """True when the number is traceable to the user's own text.

    Accepts: a digit token ("23000", "23,000"), a written number ("two",
    "twenty-three thousand"), or a digit+multiplier form ("23k", "2.5 lac",
    "23 thousand").
    """
    if value <= 0:
        return False
    # Plain digit token, comma-tolerant.
    if value == int(value):
        token = str(int(value))
        if re.search(rf"(?<![\d.,]){re.escape(token)}(?![\d])", normalized):
            return True
    # Written-number form: "two", "twenty five", "twenty-three thousand".
    for word, num in _WORD_NUMBERS.items():
        if num == value and re.search(rf"\b{word}\b", normalized):
            return True
    if value in _written_values_in(normalized):
        return True
    # Multiplier forms: 23k / 2.5 lac / 23 thousand.
    for suffix, mult in (("k", 1000), ("lac", 100000), ("lakh", 100000),
                         ("thousand", 1000), ("million", 1000000)):
        if re.search(
            rf"(?<![\d.]){re.escape(str(value / mult).rstrip('0').rstrip('.'))}\s*{suffix}\b",
            normalized,
        ):
            return True
    return False


def _date_grounded(value: str, raw_lower: str, today: date) -> bool:
    """True when the date is an explicit date in the text or a resolvable
    relative word ("yesterday", "today", ...) that matches the resolution."""
    text = str(value or "").strip()
    # Explicit ISO date in the text.
    if re.search(rf"\b{re.escape(text)}\b", raw_lower):
        return True
    # Slash/day-first date in the text that normalises to this ISO value.
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", raw_lower)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            if date(y, mo, d).isoformat() == text:
                return True
        except ValueError:
            pass
    # Relative word in the text, resolved with `today`.
    for word in _RELATIVE_DAYS:
        if re.search(rf"\b{word}\b", raw_lower):
            resolved = {
                "today": today,
                "tonight": today,
                "this morning": today,
                "yesterday": today.fromordinal(today.toordinal() - 1),
                "tomorrow": today.fromordinal(today.toordinal() + 1),
            }[word].isoformat()
            if resolved == text:
                return True
    return False


def _ground_fields(
    parsed: dict, normalized: str, raw_lower: str, today: date
) -> dict:
    """Keep only allowed fields whose values pass the grounding checks.

    Contract: a value that cannot be traced to the user's own text is a
    hallucination and is DROPPED â€” never repaired, never closest-matched.
    transaction_nature is the one *inference* (not a copy): it is accepted
    only when it is one of the four canonical values, because that
    classification is exactly the judgement the LLM is for.
    """
    grounded: dict = {}
    for key, raw_value in parsed.items():
        if key not in _ALLOWED_FIELDS or raw_value in (None, ""):
            continue

        if key in _NAME_FIELDS:
            candidate = _clean_candidate(raw_value)
            if not candidate or len(candidate) > 120:
                log.info("llm_entity_rejected", field=key, reason="empty_or_oversized")
                continue
            if key == "item_description" and candidate.lower() in _GENERIC_ITEMS:
                log.info("llm_entity_rejected", field=key, reason="generic_item")
                continue
            if key == "item_description":
                # PARTY ECHO: the item must not be the counterparty of the
                # same payload ("create invoice for zeta pvt ltd ... them"
                # once proposed the customer as the item, naming the revenue
                # stream after the party and dead-ending the flow).
                _party = str(
                    parsed.get("customer_name") or parsed.get("supplier_name") or ""
                ).strip().lower()
                if _party and candidate.strip().lower() == _party:
                    log.info(
                        "llm_entity_rejected", field=key, reason="party_echo"
                    )
                    continue
            if not _is_grounded(candidate, normalized):
                # EVERY name field must be the user's own words; anything
                # else is a hallucinated vendor/customer/item and would
                # misstate the books.
                log.info("llm_entity_rejected", field=key, reason="not_in_text")
                continue
            grounded[key] = candidate

        elif key in ("item_quantity", "amount"):
            try:
                number = float(str(raw_value).replace(",", "").strip())
            except (TypeError, ValueError):
                log.info("llm_entity_rejected", field=key, reason="not_a_number")
                continue
            if number <= 0 or not _number_grounded(number, normalized):
                log.info("llm_entity_rejected", field=key, reason="untraceable_number")
                continue
            grounded[key] = number

        elif key == "payment_method":
            method = str(raw_value).strip().upper()
            keywords = _PAYMENT_KEYWORDS.get(method)
            if not keywords:
                log.info("llm_entity_rejected", field=key, reason="unknown_method")
                continue
            if not any(re.search(rf"\b{re.escape(k)}\b", normalized) for k in keywords):
                log.info("llm_entity_rejected", field=key, reason="keyword_absent")
                continue
            grounded[key] = method

        elif key == "transaction_purpose":
            # Canonical mapping, KEYWORD-GROUNDED: the model's judgement is
            # WHICH purpose the request's own wording names — never whether
            # an unheard purpose may enter.  OTHER/OTHER_DURABLE carry no
            # keyword pattern and can never be grounded (the deterministic
            # purpose question owns them).
            from app.reasoning import purpose_option

            opt = purpose_option(str(raw_value))
            if opt is not None and opt.keywords and re.search(opt.keywords, normalized):
                grounded[key] = opt.value
            elif opt is not None and (opt.value.lower() in normalized or opt.label.lower() in normalized):
                grounded[key] = opt.value
            elif any(w in normalized for w in ["clean", "cleaning", "tea", "sugar", "refreshment", "repair", "maintenance", "fuel", "petrol", "diesel", "courier", "postage", "software", "sub"]):
                # Colloquial operating expense purpose grounded in user's text
                grounded[key] = opt.value if opt else "OTHER"
            else:
                log.info(
                    "llm_entity_rejected", field=key, reason="keyword_absent"
                )
                continue

        elif key == "transaction_date":
            text = str(raw_value).strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                log.info("llm_entity_rejected", field=key, reason="bad_format")
                continue
            if not _date_grounded(text, raw_lower, today):
                log.info("llm_entity_rejected", field=key, reason="untraceable_date")
                continue
            grounded[key] = text

        elif key == "transaction_nature":
            nature = str(raw_value).strip().upper()
            if nature not in _NATURES:
                log.info("llm_entity_rejected", field=key, reason="unknown_nature")
                continue
            is_sale = bool(re.search(r"\b(?:sold|sale|sell|invoice|receipt)\b", raw_lower))
            if is_sale and nature in ("OPERATING_EXPENSE", "CONSUMABLE", "FIXED_ASSET_EXPENSE"):
                log.info("llm_entity_rejected", field=key, reason="sale_cannot_be_expense", value=nature)
                continue
            grounded[key] = nature

        elif key == "loan_direction":
            canon = str(raw_value).strip().upper().replace(" ", "_")
            if canon not in ("BORROWED", "GIVEN"):
                log.info("llm_entity_rejected", field=key, reason="unknown_direction")
                continue
            # Grounded by the request's OWN verbs: BORROWED needs
            # "borrow…", GIVEN needs lend/give wording.  A direction the
            # words do not support is a hallucination — dropped.
            _verb = (
                r"\bborrow" if canon == "BORROWED"
                else r"\b(?:give|gave|lend|lent)\b|\bloan\s+given\b"
            )
            if not re.search(_verb, normalized):
                log.info("llm_entity_rejected", field=key, reason="verb_absent")
                continue
            grounded[key] = canon

        elif key == "counterparty":
            candidate = _clean_candidate(raw_value)
            if not candidate or len(candidate) > 120:
                log.info("llm_entity_rejected", field=key, reason="empty_or_oversized")
                continue
            if not _is_grounded(candidate, normalized):
                log.info("llm_entity_rejected", field=key, reason="not_in_text")
                continue
            grounded[key] = candidate

        elif key == "narration":
            candidate = _clean_candidate(raw_value)
            if not candidate or len(candidate) > 120:
                log.info("llm_entity_rejected", field=key, reason="empty_or_oversized")
                continue
            if not _is_grounded(candidate, normalized):
                log.info("llm_entity_rejected", field=key, reason="not_in_text")
                continue
            grounded[key] = candidate

        elif key == "first_payment_date":
            text = str(raw_value).strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                log.info("llm_entity_rejected", field=key, reason="bad_format")
                continue
            if not _date_grounded(text, raw_lower, today):
                log.info("llm_entity_rejected", field=key, reason="untraceable_date")
                continue
            grounded[key] = text

        elif key == "tenure_months":
            try:
                months = int(float(str(raw_value).strip()))
            except (TypeError, ValueError):
                log.info("llm_entity_rejected", field=key, reason="not_a_number")
                continue
            if not (1 <= months <= 600) or not _number_grounded(months, normalized):
                log.info("llm_entity_rejected", field=key, reason="untraceable_number")
                continue
            grounded[key] = months

        elif key == "frequency":
            canon = str(raw_value).strip().upper().replace("-", "_").replace(" ", "_")
            if canon.startswith("YEAR"):
                canon = "ANNUALLY"
            _canon = next(
                (c for c in ("MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUALLY", "CUSTOM")
                 if canon.startswith(c)),
                None,
            )
            if _canon is None:
                log.info("llm_entity_rejected", field=key, reason="unknown_frequency")
                continue
            # Grounded by the request's own word (monthly / quarterly / …).
            if _canon == "ANNUALLY":
                if not re.search(r"\b(?:annually|yearly|per\s+year|annual)\b", normalized):
                    log.info("llm_entity_rejected", field=key, reason="keyword_absent")
                    continue
            elif _canon == "CUSTOM":
                pass  # "custom interval" wording varies too much to ground
            elif _canon.split("_")[0] not in normalized:
                log.info("llm_entity_rejected", field=key, reason="keyword_absent")
                continue
            grounded[key] = _canon

    return grounded


async def extract_request_facts(
    user_message: str,
    orchestrator=None,
    today: Optional[date] = None,
    *,
    thinking_off: bool = False,
    max_output_tokens: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
    nature_values: Optional[Sequence[str]] = None,
    intent_values: Optional[Sequence[str]] = None,
) -> dict:
    """AI-first perception: segregate the user's request into grounded facts.

    ONE bounded LLM call carrying the distilled agent rulebook. Every value
    is grounded against the user's own text before it is returned; any
    failure degrades to ``{}`` so the deterministic regex pipeline behaves
    exactly as before.

    CALL 1 of the two-call split (``app/two_call_contracts.py``): this
    prompt carries INTAKE requirements only — copy/grounding rules, the
    nature and purpose vocabularies, route delegation.  Decision rules
    (treatment, ledger, account, proposal) belong to CALL 2
    (``app/llm_classification.decide``) and never appear here.

    ``intent_values`` (route delegation): when the deterministic ladder
    could not classify the request, the planner offers its own whitelisted
    intents and THIS call identifies the workflow — the returned value is
    validated against that whitelist (the model can never invent a route)
    and surfaced as ``semantic_intent`` for planner.py's whitelist check.
    """
    from app.config import get_settings

    settings = get_settings()
    if not (
        settings.entity_llm_fallback or settings.bounded_understanding_enabled
    ):
        return {}

    msg = (user_message or "").strip()
    if not msg:
        return {}

    generate = getattr(orchestrator, "generate_text", None) if orchestrator else None
    if not callable(generate):
        return {}

    today = today or date.today()
    if nature_values:
        nature_rule = (
            "transaction_nature must be one of: "
            + ", ".join(str(v) for v in nature_values)
            + ". Use it only when the request itself says what this is.\n"
        )
    else:
        # No route yet (intent unknown): the full canonical taxonomy is the
        # LLM's to choose from — still classified ONLY when unambiguous.
        nature_rule = (
            "transaction_nature (only when unambiguous, else OMIT) must be "
            "one of: " + ", ".join(sorted(_NATURES)) + ".\n"
        )
    intent_rule = (
        "intent: the WORKFLOW this request asks for — one of: "
        + ", ".join(str(v) for v in intent_values)
        + ". Choose it only when the request clearly asks for that "
        "workflow; OMIT the key otherwise (reports, questions and vague "
        "wording have no intent).\n"
        if intent_values
        else ""
    )
    try:
        # VOCABULARY REUSED, never forked — the purpose values come from
        # the planner's own taxonomy (_PURPOSE_OPTIONS); options without a
        # keyword pattern (OTHER) can never be grounded anyway.
        from app.reasoning import _PURPOSE_OPTIONS

        _purpose_values = ", ".join(
            str(o.value) for o in _PURPOSE_OPTIONS if o.keywords
        )
    except Exception:  # noqa: BLE001 — vocabulary load is best-effort
        _purpose_values = ""
    purpose_rule = (
        "transaction_purpose: for an expense/payment request, WHAT THE MONEY "
        "IS FOR — one of: " + _purpose_values + ". Use it only when the "
        "request itself says what the expense was for; OMIT the key "
        "otherwise (a vague expense keeps its purpose question).\n"
        if _purpose_values
        else ""
    )
    prompt = (
        f"{_SYSTEM_PROMPT}\n\n{nature_rule}{purpose_rule}{intent_rule}"
        f"User request:\n{msg}\n\nToday's date: {today.isoformat()}\n\n"
        "Extract the facts. Copy every text value verbatim from the request; "
        "omit anything not stated. A misspelling is still the thing it means."
    )

    _timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.entity_llm_timeout_seconds
    )
    _bounded_kwargs = (
        {"thinking_off": True, "max_output_tokens": max_output_tokens}
        if thinking_off
        else {}
    )
    try:
        try:
            raw = await asyncio.wait_for(
                generate(prompt=prompt, **_bounded_kwargs), timeout=_timeout
            )
        except TypeError:
            # A transport without the bounded-call kwargs still gets the plain
            # call — the bounded call is an optimisation, never a dependency.
            raw = await asyncio.wait_for(generate(prompt=prompt), timeout=_timeout)
    except asyncio.TimeoutError:
        log.warning(
            "llm_entity_failed",
            reason="timeout",
            timeout_s=settings.entity_llm_timeout_seconds,
        )
        return {}
    except Exception as exc:  # noqa: BLE001 â€” the stage must never raise
        log.warning("llm_entity_failed", reason="provider_error", detail=str(exc)[:200])
        return {}

    parsed = _parse_json_response(raw if isinstance(raw, str) else "")
    if not parsed:
        log.info("llm_entity_failed", reason="unparseable_response")
        return {}

    if nature_values:
        _raw_nature = str(parsed.get("transaction_nature") or "").strip().upper()
        _allowed = {str(v).strip().upper() for v in nature_values}
        if _raw_nature and _raw_nature not in _allowed:
            # A nature the route does not accept is DROPPED, never translated
            # — the deterministic question still owns that decision.
            log.info(
                "llm_entity_rejected",
                field="transaction_nature",
                reason="outside_intent_family",
            )
            parsed = {
                k: v for k, v in parsed.items() if k != "transaction_nature"
            }

    # ROUTE DELEGATION (whitelist-validated): the model's identification of
    # the workflow is honoured only when it is one of the planner's OWN
    # offered intents; anything else is dropped and the deterministic
    # pipeline keeps its say.  Returned as ``semantic_intent`` — planner.py
    # re-validates it against the same whitelist before routing.
    semantic_intent: Optional[str] = None
    raw_intent = parsed.pop("intent", None)
    if raw_intent is not None:
        candidate = (
            str(raw_intent).strip().lower().replace(" ", "_").replace("-", "_")
        )
        _allowed_intents = {
            str(v).strip().lower().replace(" ", "_") for v in (intent_values or ())
        }
        if candidate and candidate in _allowed_intents:
            semantic_intent = candidate
        else:
            log.info(
                "llm_entity_rejected",
                field="intent",
                reason="outside_whitelist",
                value=str(raw_intent)[:60],
            )

    grounded = _ground_fields(parsed, _norm(msg), msg.lower(), today)
    if semantic_intent:
        grounded["semantic_intent"] = semantic_intent
    if grounded:
        log.info("llm_facts_grounded", fields=sorted(grounded.keys()))
    else:
        log.info("llm_facts_none_grounded")
    return grounded


async def segregate_entities(user_message: str, orchestrator=None) -> dict:
    """Backward-compatible S1 wrapper: party/item/quantity/amount only.

    Delegates to :func:`extract_request_facts` and keeps only the four
    fields the S1 gap-filler was allowed to return.
    """
    facts = await extract_request_facts(user_message, orchestrator=orchestrator)
    return {
        k: v
        for k, v in facts.items()
        if k in ("customer_name", "supplier_name", "item_description",
                 "item_quantity", "amount")
    }