"""The copilot has to behave like a conversation, not a keyword router.

Two defects this pins, both of which made the chat feel broken in ways no
error ever surfaced:

1. **Small-talk shortcuts swallowed real questions.** The greeting branch
   fired on `any(word in tokens)`, so "salut, ce licitații sunt în Brașov?"
   was answered with a canned introduction and the actual question was
   silently dropped. Same for "ok, și în Cluj?", which matched the thanks
   list and got "cu plăcere!".

2. **No turn ever saw the ones before it.** The frontend kept the visible
   transcript but sent only the newest message, so every follow-up arrived
   at the model with nothing to resolve "primul"/"acela"/"și în Cluj?"
   against. A conversation in appearance only.

Also guards the two statements the deterministic fallback used to assert
that are not in the law: a 5-day CNSC deadline (art. 8 alin. (1) lit. b) of
Legea 101/2016 says 7) and an "keep your bid above 80% of the estimated
value, Art. 215" rule that exists in neither that article nor anywhere else
in Legea 98/2016.
"""
import pytest

import ai_copilot
from ai_copilot import MAX_USER_PROMPT_CHARS, ProcurementAICopilot

LEADS = [
    {
        "project_title": "Modernizare DJ 103",
        "entity_name": "CJ Brasov",
        "county": "Brasov",
        "financial_value_ron": 1_200_000,
        "category": "infrastructura",
    }
]


@pytest.fixture
def no_provider(monkeypatch):
    """Forces the deterministic path, so these assertions test this
    module's own routing rather than a live model's wording."""
    monkeypatch.setattr(ai_copilot, "resolve_llm_provider", lambda: None)
    monkeypatch.setattr(ai_copilot, "list_llm_providers", lambda: [])


# ------------------------------------------------- small talk vs. content

@pytest.mark.asyncio
async def test_bare_greeting_is_answered_as_a_greeting(no_provider):
    reply = await ProcurementAICopilot().answer_copilot_query("salut", LEADS)
    assert "Copilotul AI RO-INTEL" in reply


@pytest.mark.asyncio
async def test_greeting_attached_to_a_question_answers_the_question(no_provider):
    """The regression that made the copilot look deaf."""
    reply = await ProcurementAICopilot().answer_copilot_query(
        "salut, ce licitatii sunt in Brasov?", LEADS
    )
    assert "Modernizare DJ 103" in reply
    assert "Sunt Copilotul AI RO-INTEL" not in reply


@pytest.mark.asyncio
async def test_pleasantry_prefix_does_not_hijack_a_follow_up(no_provider):
    reply = await ProcurementAICopilot().answer_copilot_query(
        "ok, si in Brasov?", LEADS, history=[{"role": "user", "content": "ce e nou?"}]
    )
    assert "Cu multă plăcere" not in reply


@pytest.mark.asyncio
async def test_does_not_reintroduce_itself_mid_conversation(no_provider):
    """A greeting on turn five is politeness, not a request to start over."""
    reply = await ProcurementAICopilot().answer_copilot_query(
        "buna ziua",
        LEADS,
        history=[
            {"role": "user", "content": "ce e in Brasov?"},
            {"role": "assistant", "content": "Un dosar."},
        ],
    )
    assert "Sunt Copilotul AI RO-INTEL" not in reply


# ---------------------------------------------------- conversation memory

@pytest.mark.asyncio
async def test_history_reaches_the_provider_as_real_turns(monkeypatch):
    sent = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "răspuns"}}]}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent["messages"] = kwargs["json"]["messages"]
            return _FakeResponse()

    monkeypatch.setattr(ai_copilot, "resolve_llm_provider", lambda: ("https://x", "m", "k"))
    monkeypatch.setattr(
        ai_copilot, "list_llm_providers", lambda: [("groq", "https://x", "model", "key")]
    )
    monkeypatch.setattr(ai_copilot.httpx, "AsyncClient", lambda **kw: _FakeClient())

    reply = await ProcurementAICopilot().answer_copilot_query(
        "si in Cluj?",
        LEADS,
        history=[
            {"role": "user", "content": "ce licitatii sunt in Brasov?"},
            {"role": "assistant", "content": "Modernizare DJ 103."},
        ],
    )

    assert reply == "răspuns"
    roles = [m["role"] for m in sent["messages"]]
    # system, then the two prior turns in order, then the live question.
    assert roles == ["system", "user", "assistant", "user"]
    assert sent["messages"][1]["content"] == "ce licitatii sunt in Brasov?"
    assert sent["messages"][2]["content"] == "Modernizare DJ 103."
    assert "si in Cluj?" in sent["messages"][-1]["content"]


def test_conversation_is_bounded_from_the_front():
    """The newest turn is what the user is waiting on, so it survives; the
    oldest turns are what get dropped."""
    messages = [
        {"role": "user", "content": "x" * MAX_USER_PROMPT_CHARS},
        {"role": "assistant", "content": "y" * MAX_USER_PROMPT_CHARS},
        {"role": "user", "content": "întrebarea curentă"},
    ]
    bounded = ai_copilot._bound_conversation(messages)
    assert bounded[-1]["content"] == "întrebarea curentă"
    assert sum(len(m["content"]) for m in bounded) <= MAX_USER_PROMPT_CHARS


# ------------------------------------------------------- legal correctness

@pytest.mark.asyncio
async def test_price_answer_does_not_invent_an_80_percent_threshold(no_provider):
    reply = await ProcurementAICopilot().answer_copilot_query(
        "cat discount pot da la pret?", LEADS
    )
    assert "80%" not in reply
    # Art. 215 is not the abnormally-low-price article.
    assert "215" not in reply
    assert "210" in reply


@pytest.mark.asyncio
async def test_cnsc_deadline_is_the_one_in_the_statute(no_provider):
    reply = await ProcurementAICopilot().answer_copilot_query(
        "care e termenul de contestatie la CNSC?", LEADS
    )
    # The sub-threshold filing deadline is 7 days (art. 8 alin. (1) lit. b),
    # not the 5 the hardcoded answer used to give. Asserted on the presence
    # of 7 rather than the absence of 5: "5 zile" legitimately appears in
    # art. 4 alin. (4) as the court's own ruling deadline, which is a
    # different figure and belongs in the quotation.
    assert "7 zile" in reply
    assert "art. 8" in reply


@pytest.mark.asyncio
async def test_deadline_is_still_right_without_the_knowledge_base(no_provider, monkeypatch):
    """The last-resort branch, reached when data/legal_kb.json has not been
    built — it carries the deadlines as prose, so it has to carry them
    correctly rather than relying on the grounding above to cover it."""
    monkeypatch.setattr(ai_copilot, "_legal_grounding", lambda *a, **kw: "")
    reply = await ProcurementAICopilot().answer_copilot_query(
        "care e termenul de contestatie la CNSC?", LEADS
    )
    assert "10 zile" in reply and "7 zile" in reply
    assert "5 zile" not in reply


def test_legal_grounding_only_attaches_for_legal_questions():
    """A blanket injection would carry two pages of statute into every
    provider call and hit the free-tier tokens-per-minute ceiling, which
    binds long before any context window does."""
    assert ai_copilot._legal_grounding("ce e nou in Brasov?") == ""
    grounded = ai_copilot._legal_grounding("cum justific un pret neobisnuit de scazut?")
    assert "art. 210" in grounded
