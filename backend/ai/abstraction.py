"""AI abstraction layer — all LLM calls go through here.

Never import google.genai, anthropic, or openai in module code.
Use the functions in this module instead.
"""

import asyncio
import json
import logging
import re

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger("barkain.ai")


# MARK: - Configuration

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Return (and lazily create) the Gemini client."""
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


# MARK: - Gemini


async def gemini_generate(
    prompt: str,
    *,
    model: str = "gemini-2.0-flash",
    temperature: float = 0.1,
    max_output_tokens: int = 1024,
    max_retries: int = 1,
    retry_delay: float = 1.0,
) -> str:
    """Send a prompt to Gemini and return the text response.

    Args:
        prompt: The prompt text to send.
        model: Gemini model name.
        temperature: Sampling temperature (low for factual lookups).
        max_output_tokens: Maximum response length.
        max_retries: Number of retries on transient failures.
        retry_delay: Base delay in seconds between retries (doubles each retry).

    Returns:
        Raw text response from Gemini.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception: If all retries exhausted.
    """
    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return response.text
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "Gemini call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


async def gemini_generate_json(
    prompt: str,
    *,
    model: str = "gemini-2.0-flash",
    temperature: float = 0.1,
    max_output_tokens: int = 1024,
    max_retries: int = 1,
    retry_delay: float = 1.0,
) -> dict:
    """Send a prompt to Gemini and parse the response as JSON.

    Calls gemini_generate() then parses the result. Strips markdown
    code fences (```json ... ```) if present.

    Returns:
        Parsed JSON as a dict.

    Raises:
        ValueError: If response is not valid JSON after cleanup.
    """
    raw = await gemini_generate(
        prompt,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )

    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Gemini response as JSON: %s", raw[:200])
        raise ValueError(f"Gemini response is not valid JSON: {exc}") from exc
