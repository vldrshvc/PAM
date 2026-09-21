"""Thin wrapper around an OpenAI-compatible chat endpoint.

Two methods, one job each: send a prompt (optionally with a picture) and
return the text. Every provider quirk and SDK exception stays in here so the
rest of the app only ever sees LLMUnavailableError or a string.
"""

import base64
import logging
import time

import openai
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    """No API key in the environment; categorization is switched off."""


class LLMUnavailableError(RuntimeError):
    """The provider rejected or failed the request."""


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float) -> None:
        self._model = model
        # max_retries=1: a categorization is cheap to retry once, but the
        # user is waiting, so we don't hang around for the SDK default of 2.
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1)

    def complete(self, system: str, user: str, max_tokens: int = 30) -> str:
        return self._chat(system, user, max_tokens=max_tokens)

    def read_image(
        self, system: str, user: str, image: bytes, media_type: str, max_tokens: int | None = None
    ) -> str:
        """Same call with a picture attached, inline as a data URL.

        Inline rather than uploaded: the photo is a receipt the user does not
        want kept, and a data URL leaves nothing behind at the provider to
        delete afterwards.
        """
        data_url = f"data:{media_type};base64,{base64.b64encode(image).decode()}"
        return self._chat(
            system,
            [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            max_tokens=max_tokens or settings.llm_vision_max_tokens,
        )

    def _chat(self, system: str, user: object, max_tokens: int) -> str:
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                max_tokens=max_tokens,
            )
        except openai.APITimeoutError as exc:
            raise LLMUnavailableError("LLM provider timed out") from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailableError("Could not connect to LLM provider") from exc
        except openai.APIStatusError as exc:
            raise LLMUnavailableError(f"LLM provider returned HTTP {exc.status_code}") from exc
        choice = response.choices[0] if response.choices else None
        content = (choice.message.content if choice else None) or ""
        usage = response.usage
        # A cut-off answer is not a bad answer, it is no answer: whatever
        # parses it would be guessing at half a sentence.
        if choice is not None and choice.finish_reason == "length":
            logger.warning("llm answer truncated at max_tokens=%s: %r", max_tokens, content)
            raise LLMUnavailableError("The model's answer was cut off")
        # One line per call so provider behaviour (latency, truncation,
        # hidden reasoning tokens) is visible in the server log.
        logger.info(
            "llm model=%s latency=%.2fs finish=%s completion_tokens=%s answer=%r",
            self._model,
            time.monotonic() - started,
            choice.finish_reason if choice else None,
            usage.completion_tokens if usage else None,
            content[:200],
        )
        return content


def get_llm_client() -> LLMClient:
    if not settings.llm_api_key:
        raise LLMNotConfiguredError("LLM_API_KEY is not set")
    return LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )


def get_vision_client() -> LLMClient:
    """The same wrapper pointed at a model that accepts images."""
    if not settings.llm_api_key:
        raise LLMNotConfiguredError("LLM_API_KEY is not set")
    return LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_vision_model,
        timeout=settings.llm_vision_timeout_seconds,
    )
