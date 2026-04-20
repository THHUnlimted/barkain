"""Tests for ``scripts/generate_autocomplete_vocab.py``.

Mocks Amazon's autocomplete endpoint via respx so we never hit the
network. The opt-in real-API smoke test at the bottom is gated on
``BARKAIN_RUN_NETWORK_TESTS=1`` (mirrors the project's integration-test
gating convention from docs/TESTING.md §8).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_autocomplete_vocab.py"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "amazon_suggestions_ipho.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "generate_autocomplete_vocab", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_autocomplete_vocab"] = module
    spec.loader.exec_module(module)
    return module


gav = _load_module()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Replace the script's async sleep with a no-op call counter."""

    async def _fast_sleep(_seconds: float) -> None:
        _fast_sleep.calls.append(_seconds)  # type: ignore[attr-defined]

    _fast_sleep.calls = []  # type: ignore[attr-defined]
    monkeypatch.setattr(gav, "_async_sleep", _fast_sleep)
    return _fast_sleep


@pytest.fixture
def fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def fresh_cache_dir(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    return cache


# MARK: - 1. Amazon JSON shape parses

@respx.mock
async def test_fetch_amazon_parses_real_response_shape(fixture_payload: dict):
    respx.get("https://completion.amazon.com/api/2017/suggestions").mock(
        return_value=httpx.Response(200, json=fixture_payload)
    )
    async with httpx.AsyncClient() as client:
        values, uppers = await gav.fetch_amazon(client, "amazon_aps", "ipho")
    assert "iphone 17 pro max case" in values
    assert "iphone 17 pro max" in values
    assert "  iPhone 17 Pro!  " in values
    assert uppers == set()  # no all-uppercase short tokens in fixture


# MARK: - 2. Normalization round-trip + idempotency

def test_normalize_strips_outer_punct_collapses_spaces():
    assert gav.normalize("  iPhone 17 Pro!  ") == "iphone 17 pro"
    assert gav.normalize(",,Sony WH-1000XM5..") == "sony wh-1000xm5"


def test_normalize_idempotent():
    once = gav.normalize("  iPhone 17 Pro!  ")
    twice = gav.normalize(once)
    assert once == twice


# MARK: - 3. Dedup + frequency scoring

def test_term_accumulator_scores_by_distinct_prefixes():
    acc = gav.TermAccumulator()
    acc.record("Sony WH-1000XM5", "amazon_aps", "so")
    acc.record("Sony WH-1000XM5", "amazon_aps", "son")
    acc.record("Sony WH-1000XM5", "amazon_aps", "sony")
    # Same (source, prefix) tuple recorded twice should not double-count.
    acc.record("sony wh-1000xm5", "amazon_aps", "sony")
    occurrences = acc.occurrences["sony wh-1000xm5"]
    assert len(occurrences) == 3


# MARK: - 4. Electronics filter — positive / negative / brand / model

@pytest.mark.parametrize(
    "term,source,expected",
    [
        ("iphone 17 pro max", "amazon_aps", True),
        ("apple watch series 10", "amazon_aps", True),
        ("rtx 4090", "amazon_aps", True),
        ("sony wh-1000xm5", "amazon_aps", True),
        ("western digital ssd", "amazon_aps", True),
        ("hard drive 2tb", "amazon_aps", True),
        ("cat food", "amazon_aps", False),
        ("baby diapers", "amazon_aps", False),
        # Source-scoped pass: even non-electronics text passes when source
        # is electronics-scoped (we trust Amazon's department filter).
        ("phone charger lotion", "amazon_electronics", True),
    ],
)
def test_electronics_filter(term: str, source: str, expected: bool):
    assert gav.is_electronics(term, source) is expected


# MARK: - 5. --max-terms cap

def test_assemble_terms_caps_at_max():
    acc = gav.TermAccumulator()
    # Build 12 distinct iphone variants with descending scores.
    for i in range(12):
        for j in range(i + 1):  # term i appears under (i+1) distinct prefixes
            acc.record(f"iphone {i}", "amazon_aps", f"p{j}")
    stats = gav.SweepStats()
    terms = gav.assemble_terms(acc, stats, max_terms=5)
    assert len(terms) == 5
    # Highest score is iphone 11 (12 prefixes), descending.
    scores = [t["s"] for t in terms]
    assert scores == sorted(scores, reverse=True)


# MARK: - 6. Throttle respected (sleep called between requests)

@respx.mock
async def test_throttle_invokes_sleep_per_request(
    fixture_payload: dict, _no_real_sleep, fresh_cache_dir: Path
):
    respx.get("https://completion.amazon.com/api/2017/suggestions").mock(
        return_value=httpx.Response(200, json=fixture_payload)
    )
    acc = gav.TermAccumulator()
    stats = gav.SweepStats()
    async with httpx.AsyncClient() as client:
        await gav.sweep_source(
            client,
            "amazon_aps",
            ["a", "b", "c"],
            acc,
            stats,
            throttle=0.1,
            cache_dir=fresh_cache_dir,
            resume=False,
        )
    # One sleep per fresh fetch (we never hit the cache). 3 prefixes → ≥2 sleeps
    # (last one is harmless).
    assert sum(1 for s in _no_real_sleep.calls if s == 0.1) >= 2


# MARK: - 7. Retry on 429 → eventual 200

@respx.mock
async def test_amazon_retries_on_429_then_succeeds(fixture_payload: dict):
    route = respx.get("https://completion.amazon.com/api/2017/suggestions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(200, json=fixture_payload),
    ]
    async with httpx.AsyncClient() as client:
        values, _ = await gav.fetch_amazon(client, "amazon_aps", "ipho")
    assert any("iphone" in v.lower() for v in values)
    assert route.call_count == 3


# MARK: - 8. Resume from cache: no HTTP call when prefix is cached

@respx.mock
async def test_resume_skips_http_for_cached_prefix(fresh_cache_dir: Path):
    gav.write_cache(
        fresh_cache_dir, "amazon_aps", "z", ["iphone 17 pro max"]
    )
    route = respx.get("https://completion.amazon.com/api/2017/suggestions").mock(
        return_value=httpx.Response(500)  # would 500 if hit
    )
    acc = gav.TermAccumulator()
    stats = gav.SweepStats()
    async with httpx.AsyncClient() as client:
        await gav.sweep_source(
            client,
            "amazon_aps",
            ["z"],
            acc,
            stats,
            throttle=0.0,
            cache_dir=fresh_cache_dir,
            resume=True,
        )
    assert route.call_count == 0
    assert "iphone 17 pro max" in acc.occurrences


# MARK: - 9. JSON output schema + score-desc sort

def test_build_output_payload_schema_and_sort():
    acc = gav.TermAccumulator()
    acc.record("iphone 17 pro", "amazon_aps", "ip")
    acc.record("iphone 17 pro", "amazon_aps", "iph")
    acc.record("airpods pro 2", "amazon_aps", "air")
    stats = gav.SweepStats(total_prefixes_swept=3, raw_suggestions=3)
    terms = gav.assemble_terms(acc, stats, max_terms=10)
    payload = gav.build_output_payload(terms, stats, sources=["amazon_aps"])
    assert payload["version"] == 1
    assert set(payload).issuperset(
        {"version", "generated_at", "git_commit", "sources", "stats", "terms"}
    )
    # Score desc — iphone has 2, airpods has 1.
    assert payload["terms"][0]["t"].lower().startswith("iphone")
    assert payload["terms"][0]["s"] == 2
    assert payload["terms"][1]["s"] == 1
    # Stats populated.
    assert payload["stats"]["after_dedup"] == 2
    assert payload["stats"]["after_electronics_filter"] == 2


# MARK: - 10. --dry-run writes nothing

@respx.mock
async def test_dry_run_does_not_write_output(
    fixture_payload: dict, tmp_path: Path
):
    respx.get("https://completion.amazon.com/api/2017/suggestions").mock(
        return_value=httpx.Response(200, json=fixture_payload)
    )
    out = tmp_path / "vocab.json"
    cache = tmp_path / "cache"
    args = gav.parse_args(
        [
            "--sources", "amazon_aps",
            "--prefix-depth", "1",
            "--throttle", "0",
            "--max-terms", "10",
            "--output", str(out),
            "--cache-dir", str(cache),
            "--dry-run",
        ]
    )
    rc = await gav.run(args)
    assert rc == 0
    assert not out.exists()


# MARK: - 11. Best Buy / eBay graceful skip on shape drift

@respx.mock
async def test_bestbuy_skips_on_shape_drift():
    respx.get("https://www.bestbuy.com/autocomplete/searches").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(gav.SourceShapeError):
            await gav.fetch_bestbuy(client, "bestbuy", "iph")


@respx.mock
async def test_ebay_skips_on_missing_field():
    respx.get("https://autosug.ebay.com/autosug").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(gav.SourceShapeError):
            await gav.fetch_ebay(client, "ebay", "iph")


# MARK: - 12. End-to-end run() writes a valid file

@respx.mock
async def test_run_end_to_end_writes_valid_json(
    fixture_payload: dict, tmp_path: Path
):
    respx.get("https://completion.amazon.com/api/2017/suggestions").mock(
        return_value=httpx.Response(200, json=fixture_payload)
    )
    out = tmp_path / "vocab.json"
    cache = tmp_path / "cache"
    args = gav.parse_args(
        [
            "--sources", "amazon_aps",
            "--prefix-depth", "1",
            "--throttle", "0",
            "--max-terms", "100",
            "--output", str(out),
            "--cache-dir", str(cache),
        ]
    )
    rc = await gav.run(args)
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["terms"], "expected at least one term"
    # All output terms are display-cased (not raw lowercase or whitespace).
    for entry in payload["terms"]:
        assert entry["t"] == entry["t"].strip()
        assert entry["t"][0].isupper() or entry["t"][0].isdigit()


# MARK: - 13. Display casing preserves short uppercase tokens

def test_display_case_preserves_short_uppercase():
    # "PS5" is 3 chars, all-uppercase in the source — should stay PS5.
    assert (
        gav.display_case("ps5 console", preserve_upper={"ps5"})
        == "PS5 Console"
    )
    # "iphone" is not preserved-upper; gets Title Cased.
    assert gav.display_case("iphone 17 pro", preserve_upper=set()) == "Iphone 17 Pro"


# MARK: - Real-API smoke (opt-in)

pytestmark_smoke = pytest.mark.skipif(
    os.environ.get("BARKAIN_RUN_NETWORK_TESTS") != "1",
    reason="Set BARKAIN_RUN_NETWORK_TESTS=1 to hit live Amazon",
)


@pytestmark_smoke
async def test_real_amazon_endpoint_returns_iphone_for_iph_prefix():
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        headers={"User-Agent": gav.USER_AGENT},
    ) as client:
        values, _ = await gav.fetch_amazon(client, "amazon_aps", "iph")
    assert values, "Amazon returned no suggestions"
    assert any("iphone" in v.lower() for v in values), values[:5]
