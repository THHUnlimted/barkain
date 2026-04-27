"""Tests for AI abstraction layer — Claude/Anthropic integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# MARK: - claude_generate


@pytest.mark.asyncio
async def test_claude_generate_returns_text():
    """Given a valid prompt, claude_generate returns extracted text."""
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Hello from Claude"
    mock_response.content = [mock_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_anthropic_client", return_value=mock_client):
        from ai.abstraction import claude_generate

        result = await claude_generate("test prompt", max_retries=0)
        assert result == "Hello from Claude"
        mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_claude_generate_json_strips_fences():
    """Given a markdown-fenced JSON response, parse correctly."""
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = '```json\n{"key": "value"}\n```'
    mock_response.content = [mock_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_anthropic_client", return_value=mock_client):
        from ai.abstraction import claude_generate_json

        result = await claude_generate_json("test prompt", max_retries=0)
        assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_claude_generate_retries_on_failure():
    """Given a transient failure, retry before raising."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=[
            Exception("Connection error"),
            _make_mock_response("retry succeeded"),
        ]
    )

    with patch("ai.abstraction._get_anthropic_client", return_value=mock_client):
        from ai.abstraction import claude_generate

        result = await claude_generate("test", max_retries=1, retry_delay=0.01)
        assert result == "retry succeeded"
        assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_claude_generate_json_with_usage_returns_tokens():
    """Given a valid response, return parsed JSON and token count."""
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = json.dumps({"extract_js": "new code", "changes": [], "confidence": 0.9})
    mock_response.content = [mock_block]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_anthropic_client", return_value=mock_client):
        from ai.abstraction import claude_generate_json_with_usage

        result, tokens = await claude_generate_json_with_usage("test", max_retries=0)
        assert result["extract_js"] == "new code"
        assert tokens == 150


# MARK: - gemini_generate (config-shape regression tests)


@pytest.mark.asyncio
async def test_gemini_generate_uses_thinking_level_low():
    """Pin: gemini_generate uses ThinkingLevel.LOW, not dynamic budget.

    Tied to the bench/mini-a-vs-b → feat/grounded-low-thinking change. Ground-
    truth recall verified equivalent on UPCitemdb-validated UPCs (4 Apple
    AirPods + 1 Samsung Galaxy Buds, A vs B identical 8/10), cost per call
    drops ~37 % at the Gemini billing layer. If this assertion fails the
    next time someone touches abstraction.py, re-read the bench artifact
    before flipping back.
    """
    from google.genai.types import ThinkingLevel

    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "stub"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_gemini_client", return_value=mock_client):
        from ai.abstraction import gemini_generate

        await gemini_generate("test prompt", max_retries=0)

    mock_client.aio.models.generate_content.assert_called_once()
    config = mock_client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.thinking_config.thinking_level == ThinkingLevel.LOW
    assert config.thinking_config.thinking_budget is None, (
        "thinking_budget must be unset when thinking_level is in use — "
        "passing both at once is undefined behavior in the SDK"
    )


@pytest.mark.asyncio
async def test_gemini_generate_keeps_grounding_enabled():
    """Pin: gemini_generate keeps the google_search Tool wired up.

    The bench established equivalent recall under LOW thinking *only when
    grounding stays on*. Stripping the tool would silently regress the UPC
    lookup leg to non-grounded synthesis (config C/D in the bench, which
    hallucinated MacBooks for AirPods UPCs).
    """
    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "stub"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_gemini_client", return_value=mock_client):
        from ai.abstraction import gemini_generate

        await gemini_generate("test prompt", max_retries=0)

    config = mock_client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.tools is not None and len(config.tools) == 1
    tool = config.tools[0]
    assert tool.google_search is not None


# MARK: - gemini_generate (vendor-migrate-1 synthesis-path regression tests)


@pytest.mark.asyncio
async def test_gemini_generate_grounded_false_omits_tool():
    """Pin: grounded=False removes the google_search Tool.

    The Serper-then-synthesis path in ai/web_search.py needs a non-grounded
    Gemini call so the model uses ONLY the Serper snippets. If grounded
    accidentally stays on, the model can ignore the snippets and run its
    own search — which is what B already does.
    """
    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "stub"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_gemini_client", return_value=mock_client):
        from ai.abstraction import gemini_generate

        await gemini_generate("test prompt", grounded=False, max_retries=0)

    config = mock_client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.tools is None, (
        "grounded=False must omit the Tool — otherwise synthesis call "
        "will run its own grounded search and ignore Serper snippets"
    )


@pytest.mark.asyncio
async def test_gemini_generate_thinking_budget_zero_disables_thinking():
    """Pin: thinking_budget=0 wires ThinkingConfig(thinking_budget=0).

    The Serper-then-synthesis path uses thinking_budget=0 — the bench
    showed budgets 256-1024 actually HURT recall on clean SERP snippets.
    Setting budget=0 forces direct snippet extraction. If this regresses,
    the synthesis path will get slower AND less accurate at the same time.
    """
    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "stub"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_gemini_client", return_value=mock_client):
        from ai.abstraction import gemini_generate

        await gemini_generate("test prompt", thinking_budget=0, max_retries=0)

    config = mock_client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.thinking_config.thinking_budget == 0
    assert config.thinking_config.thinking_level is None, (
        "thinking_level must be unset when thinking_budget is in use — "
        "passing both at once is undefined behavior in the SDK"
    )


@pytest.mark.asyncio
async def test_gemini_generate_respects_temperature_parameter():
    """Pin: gemini_generate uses the temperature parameter, not a hardcoded value.

    Before vendor-migrate-1, abstraction.py:gemini_generate hardcoded
    temperature=1.0 inside GenerateContentConfig, ignoring the parameter.
    UPC lookup is a fact-finding task that needs determinism — temperature
    1.0 was masking real recall by injecting variance run-over-run. Bench
    measured B with temperature=0.1 (via its own _gemini_call); production
    was running at 1.0 — vendor-migrate-1 brings them into agreement.
    """
    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "stub"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("ai.abstraction._get_gemini_client", return_value=mock_client):
        from ai.abstraction import gemini_generate

        await gemini_generate("test prompt", temperature=0.1, max_retries=0)

    config = mock_client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0.1, (
        "temperature parameter must propagate to GenerateContentConfig — "
        "the prior hardcoded 1.0 was a long-standing bug fixed in vendor-migrate-1"
    )


# MARK: - Helpers


def _make_mock_response(text: str) -> MagicMock:
    mock = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    mock.content = [block]
    return mock
