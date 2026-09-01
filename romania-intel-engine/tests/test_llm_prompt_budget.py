"""The user half of an LLM prompt must stay bounded.

Two routes accept unbounded free text from a caller and forward it into a
provider prompt: the copilot's `query` (api.py's CopilotQueryRequest) and
the clarification generator's `clarification_points` (routers/drafting.py).
Neither Pydantic model declares a max_length.

The failure mode this guards is quiet, which is why it needs a test. It is
not the context window — those are 128k+ on every configured model. It is
the free-tier tokens-per-minute ceiling on Groq and Gemini: an oversized
prompt is rejected by each provider in turn, complete_text returns None,
and every caller treats None as "the optional AI expansion simply didn't
happen" and returns its template output. Nothing raises, nothing 500s, and
the user sees a plausible document that silently skipped the AI pass.
"""
import pytest

import ai_copilot
from ai_copilot import MAX_USER_PROMPT_CHARS, complete_text


def test_short_prompt_is_untouched():
    prompt = "Care sunt riscurile acestui caiet de sarcini?"
    assert ai_copilot._bound_user_prompt(prompt) == prompt


def test_oversized_prompt_is_truncated_and_flagged():
    bounded = ai_copilot._bound_user_prompt("a" * (MAX_USER_PROMPT_CHARS * 5))
    assert len(bounded) < MAX_USER_PROMPT_CHARS * 5
    # The model must be told its input is partial, so a truncated document
    # cannot come back as a confident answer about the whole thing.
    assert "trunchiat automat" in bounded


@pytest.mark.asyncio
async def test_cap_is_enforced_at_the_choke_point(monkeypatch):
    """Every caller reaches a provider through complete_text, so the bound
    belongs there — a new route must not be able to bypass it by forgetting
    to slice its own input."""
    sent = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent["messages"] = kwargs["json"]["messages"]
            return _FakeResponse()

    monkeypatch.setattr(
        ai_copilot, "list_llm_providers", lambda: [("groq", "https://x", "model", "key")]
    )
    monkeypatch.setattr(ai_copilot.httpx, "AsyncClient", lambda **kw: _FakeClient())

    result = await complete_text("SYSTEM RULES", "b" * (MAX_USER_PROMPT_CHARS * 3))

    assert result == "ok"
    user_message = next(m for m in sent["messages"] if m["role"] == "user")
    assert len(user_message["content"]) <= MAX_USER_PROMPT_CHARS + len(ai_copilot._TRUNCATION_NOTICE)
    # The system prompt carries the legal grounding and anti-hallucination
    # rules — cutting it would hurt far more than losing an input's tail.
    system_message = next(m for m in sent["messages"] if m["role"] == "system")
    assert system_message["content"] == "SYSTEM RULES"
