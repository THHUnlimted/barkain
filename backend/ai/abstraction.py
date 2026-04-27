"""AI abstraction layer — all LLM calls go through here.

Never import google.genai, anthropic, or openai in module code.
Use the functions in this module instead.
"""

import asyncio
import json
import logging
import re

import anthropic
from google import genai
from google.genai import types
from google.genai.types import GoogleSearch, ThinkingConfig, ThinkingLevel, Tool

from app.config import settings

logger = logging.getLogger("barkain.ai")


# MARK: - Gemini Configuration

_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    """Return (and lazily create) the Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


# MARK: - Anthropic Configuration

_anthropic_client: anthropic.AsyncAnthropic | None = None


def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    """Return (and lazily create) the Anthropic async client."""
    global _anthropic_client
    if _anthropic_client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


# MARK: - Helpers


def _extract_text(response) -> str:
    """Extract only the model's text output, skipping thinking/grounding parts."""
    if not response.candidates:
        return response.text  # fallback to default

    parts = response.candidates[0].content.parts
    text_parts = []
    for part in parts:
        # Skip thinking parts (have a "thought" attribute set to True)
        if getattr(part, "thought", False):
            continue
        if part.text:
            text_parts.append(part.text)

    if text_parts:
        return "\n".join(text_parts)

    # Fallback if no text parts found
    return response.text


# MARK: - Gemini


async def gemini_generate(
    prompt: str,
    *,
    model: str = "gemini-3.1-flash-lite-preview",
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    max_retries: int = 1,
    retry_delay: float = 1.0,
    system_instruction: str | None = None,
    grounded: bool = True,
    thinking_budget: int | None = None,
) -> str:
    """Send a prompt to Gemini and return the text response.

    Args:
        prompt: The prompt text to send.
        model: Gemini model name.
        temperature: Sampling temperature (low for factual lookups).
        max_output_tokens: Maximum response length.
        max_retries: Number of retries on transient failures.
        retry_delay: Base delay in seconds between retries (doubles each retry).
        system_instruction: Optional system instruction for the model.
        grounded: When True (default), wires Tool(google_search=GoogleSearch())
            so Gemini can issue real-time web searches. Set False for the
            Serper-then-synthesis path in ai/web_search.py.
        thinking_budget: When None (default), uses ThinkingLevel.LOW (PR #75).
            When set to an integer, uses ThinkingConfig(thinking_budget=N) —
            0 disables thinking entirely, -1 = dynamic. Used by the synthesis
            path which bench-validated thinking_budget=0 as the cheapest
            winning configuration (vendor-migrate-1).

    Returns:
        Raw text response from Gemini.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception: If all retries exhausted.
    """
    client = _get_gemini_client()

    if thinking_budget is None:
        tc = ThinkingConfig(thinking_level=ThinkingLevel.LOW)
    else:
        tc = ThinkingConfig(thinking_budget=thinking_budget)

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        system_instruction=system_instruction,
        thinking_config=tc,
        tools=[Tool(google_search=GoogleSearch())] if grounded else None,
    )

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            # Extract only text parts, skipping thinking and grounding chunks
            return _extract_text(response)
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
    model: str = "gemini-3.1-flash-lite-preview",
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    max_retries: int = 1,
    retry_delay: float = 1.0,
    system_instruction: str | None = None,
    grounded: bool = True,
    thinking_budget: int | None = None,
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
        system_instruction=system_instruction,
        grounded=grounded,
        thinking_budget=thinking_budget,
    )

    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Response may be truncated or contain extra fields — try to extract
        # the first complete JSON object from the text
        match = re.search(r"\{[^{}]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.error("Failed to parse Gemini response as JSON: %s", raw[:500])
        raise ValueError(f"Gemini response is not valid JSON: {raw[:200]}")


# MARK: - Claude / Anthropic


async def claude_generate(
    prompt: str,
    *,
    model: str = "claude-opus-4-0",
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    max_retries: int = 1,
    retry_delay: float = 1.0,
    system_instruction: str | None = None,
) -> str:
    """Send a prompt to Claude and return the text response.

    Args:
        prompt: The prompt text to send.
        model: Claude model name (claude-opus-4-0, claude-sonnet-4-5-20250514, etc.).
        temperature: Sampling temperature.
        max_output_tokens: Maximum response length.
        max_retries: Number of retries on transient failures.
        retry_delay: Base delay in seconds between retries (doubles each retry).
        system_instruction: Optional system instruction for the model.

    Returns:
        Raw text response from Claude.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is not configured.
        Exception: If all retries exhausted.
    """
    client = _get_anthropic_client()

    kwargs: dict = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_instruction:
        kwargs["system"] = system_instruction

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.messages.create(**kwargs)
            # Extract text from content blocks
            text_parts = [
                block.text for block in response.content if block.type == "text"
            ]
            return "\n".join(text_parts) if text_parts else ""
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "Claude call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


async def claude_generate_json(
    prompt: str,
    *,
    model: str = "claude-opus-4-0",
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    max_retries: int = 1,
    retry_delay: float = 1.0,
    system_instruction: str | None = None,
) -> dict:
    """Send a prompt to Claude and parse the response as JSON.

    Calls claude_generate() then parses the result. Strips markdown
    code fences (```json ... ```) if present.

    Returns:
        Parsed JSON as a dict.

    Raises:
        ValueError: If response is not valid JSON after cleanup.
    """
    raw = await claude_generate(
        prompt,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        retry_delay=retry_delay,
        system_instruction=system_instruction,
    )

    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.error("Failed to parse Claude response as JSON: %s", raw[:500])
        raise ValueError(f"Claude response is not valid JSON: {raw[:200]}")


async def claude_generate_json_with_usage(
    prompt: str,
    *,
    model: str = "claude-opus-4-0",
    temperature: float = 0.1,
    max_output_tokens: int = 8192,
    max_retries: int = 1,
    retry_delay: float = 1.0,
    system_instruction: str | None = None,
) -> tuple[dict, int]:
    """Like claude_generate_json but also returns total tokens used.

    Used by the Watchdog to track LLM cost in watchdog_events.

    Returns:
        Tuple of (parsed JSON dict, total tokens used).
    """
    client = _get_anthropic_client()

    kwargs: dict = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_instruction:
        kwargs["system"] = system_instruction

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.messages.create(**kwargs)
            text_parts = [
                block.text for block in response.content if block.type == "text"
            ]
            raw = "\n".join(text_parts) if text_parts else ""
            total_tokens = response.usage.input_tokens + response.usage.output_tokens

            # Parse JSON
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)

            try:
                return json.loads(cleaned), total_tokens
            except json.JSONDecodeError:
                match = re.search(r"\{[^{}]*\}", cleaned)
                if match:
                    try:
                        return json.loads(match.group()), total_tokens
                    except json.JSONDecodeError:
                        pass

                logger.error("Failed to parse Claude response as JSON: %s", raw[:500])
                raise ValueError(f"Claude response is not valid JSON: {raw[:200]}")
        except ValueError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "Claude call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
