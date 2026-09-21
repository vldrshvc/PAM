"""The provider wrapper itself: what it does with an answer that isn't one."""

from types import SimpleNamespace

import pytest

from app.llm import LLMClient, LLMUnavailableError


def stub_response(client: LLMClient, content: str, finish_reason: str) -> None:
    """Put a scripted completion in front of the SDK call."""
    response = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(completion_tokens=7),
    )
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
    )


@pytest.fixture
def client() -> LLMClient:
    return LLMClient(api_key="not-a-key", base_url="http://localhost:1/v1/", model="m", timeout=1)


def test_a_truncated_answer_is_not_an_answer(client):
    # Half an object parses as nothing, and a model that thinks before it
    # replies can spend the whole budget before the JSON starts. Saying so is
    # worth more than a generic "could not read this".
    stub_response(client, '{"total": "57.9', finish_reason="length")

    with pytest.raises(LLMUnavailableError, match="cut off"):
        client.read_image("system", "user", b"jpeg bytes", "image/jpeg")


def test_a_complete_answer_comes_back(client):
    stub_response(client, '{"total": "57.90"}', finish_reason="stop")

    assert client.read_image("system", "user", b"jpeg bytes", "image/jpeg") == '{"total": "57.90"}'


def test_the_configured_budget_is_what_gets_sent(client, monkeypatch):
    # A reasoning model spends this thinking before it writes anything, so the
    # budget has to cover the thinking, not just the sixty-token answer.
    from app.config import settings

    monkeypatch.setattr(settings, "llm_vision_max_tokens", 1234)
    sent = {}

    def capture(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))],
            usage=None,
        )

    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture))
    )
    client.read_image("system", "user", b"jpeg bytes", "image/jpeg")

    assert sent["max_tokens"] == 1234


def test_the_picture_is_sent_inline_with_its_media_type(client):
    sent = {}

    def capture(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))],
            usage=None,
        )

    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture))
    )
    client.read_image("system", "user", b"jpeg bytes", "image/webp")

    parts = sent["messages"][1]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["image_url"]["url"].startswith("data:image/webp;base64,")
