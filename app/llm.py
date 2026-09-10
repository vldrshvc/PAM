"""Thin wrapper around an OpenAI-compatible chat endpoint.

One method, one job: send a system + user prompt, return the text. Every
provider quirk and SDK exception stays in here so the rest of the app only
ever sees LLMUnavailableError or a string.
"""

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
        # One line per call so provider behaviour (latency, truncation,
        # hidden reasoning tokens) is visible in the server log.
        logger.info(
            "llm model=%s latency=%.2fs finish=%s completion_tokens=%s answer=%r",
            self._model,
            time.monotonic() - started,
            choice.finish_reason if choice else None,
            usage.completion_tokens if usage else None,
            content[:60],
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
