"""Regression guards on extract.sh timing optimizations.

These containers (target, home_depot, backmarket, lowes) don't have
PerimeterX/DataDome/Akamai-class bot protection, so the homepage warmup +
heavy jitter values that ship with the template scraper are pure latency
waste. This test locks in the timing optimizations from the 2026-04-17
demo-prep-3 branch so the wins don't accidentally regress in a future
"let's add jitter back for safety" cleanup.

Does NOT guard target's `load` (not `networkidle`) wait strategy — that's
tested implicitly via extraction correctness and is a stable invariant.
Does NOT guard the samsclub/amazon/bestbuy/walmart scripts — those have
real anti-bot requirements that need the warmup + jitter noise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONTAINERS_DIR = Path(__file__).resolve().parents[3] / "containers"

# Homepage warmup is safe to remove on target + backmarket — they don't
# depend on session cookies for search to render product grids.
# home_depot + lowes DO depend on warmup — measured 2026-04-17 that
# skipping it drops listings 3 → 0 (location-picker / empty-results
# fallback without homepage-set cookies). Keep warmup on those.
WARMUP_REMOVED_RETAILERS = ["target", "backmarket"]
WARMUP_REQUIRED_RETAILERS = ["home_depot", "lowes"]
OPTIMIZED_RETAILERS = WARMUP_REMOVED_RETAILERS + WARMUP_REQUIRED_RETAILERS


@pytest.fixture(scope="module", params=OPTIMIZED_RETAILERS)
def extract_sh_text(request) -> str:
    path = CONTAINERS_DIR / request.param / "extract.sh"
    assert path.is_file(), f"extract.sh not found at {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module", params=WARMUP_REMOVED_RETAILERS)
def no_warmup_retailer_text(request) -> str:
    path = CONTAINERS_DIR / request.param / "extract.sh"
    return path.read_text(encoding="utf-8")


# MARK: - Homepage warmup


def test_warmup_removed_on_warmup_removed_retailers(
    no_warmup_retailer_text: str,
) -> None:
    """target + backmarket don't depend on session cookies — direct search
    navigation works. Expect exactly one `ab open` (the search URL)."""
    ab_open_count = no_warmup_retailer_text.count("ab open ")
    assert ab_open_count == 1, (
        f"Expected exactly one `ab open` on warmup-removed retailers, found "
        f"{ab_open_count}. A homepage warmup has been re-introduced."
    )


def test_search_url_is_navigated(extract_sh_text: str) -> None:
    assert 'ab open "$SEARCH_URL"' in extract_sh_text


# MARK: - Chromium startup sleep


def test_chromium_launch_sleep_is_trimmed(extract_sh_text: str) -> None:
    """`sleep 3` after the Chromium launch was pessimistic — CDP is ready
    in ~500ms. `sleep 1` is sufficient and saves 2s per extract."""
    # The `sleep` must appear between `about:blank" &` and the next ab call.
    assert '"about:blank" &\n  sleep 1' in extract_sh_text, (
        "Expected `sleep 1` immediately after Chromium background-launch. "
        "If you need more time, measure first — don't default to 3."
    )


# MARK: - Jitter values must be the trimmed versions


def test_pre_navigation_jitter_is_trimmed(extract_sh_text: str) -> None:
    """The pre-navigation jitter was `jitter 800 1500` — excessive bot-
    evasion noise for these sites. `jitter 200 400` is plenty."""
    assert "jitter 200 400" in extract_sh_text, (
        "Expected `jitter 200 400` as the pre-navigation delay. If you've "
        "widened the range, measure first — these sites don't reward jitter."
    )
    # The old values must be gone (except in retry cool-down, which is intentional).
    assert "jitter 800 1500" not in extract_sh_text
    assert "jitter 1500 2500" not in extract_sh_text


def test_post_search_jitter_is_trimmed(extract_sh_text: str) -> None:
    """Post-search-navigation jitter was `jitter 1500 2500` — trimmed to
    `jitter 500 1000`."""
    assert "jitter 500 1000" in extract_sh_text


# MARK: - Scroll loop count


def test_scroll_loop_is_three_not_five(extract_sh_text: str) -> None:
    """The scroll loop was `for i in 1 2 3 4 5` — 5 iterations triggered
    lazy-load beyond anything max_listings=10 could consume. 3 is enough."""
    assert "for i in 1 2 3; do" in extract_sh_text, (
        "Expected `for i in 1 2 3` in the scroll loop. Anything longer is "
        "waste at max_listings≤10 (the default). If you need more iterations "
        "for a specific retailer, take this guard off and leave a comment."
    )
    assert "for i in 1 2 3 4 5" not in extract_sh_text


def test_scroll_jitter_is_trimmed(extract_sh_text: str) -> None:
    """Per-iteration scroll jitter cut from `600 1200` → `200 400` (~2s
    saved over 3 iterations)."""
    # The trimmed value must appear (at least in the scroll loop).
    assert "jitter 200 400" in extract_sh_text
    assert "jitter 600 1200" not in extract_sh_text
