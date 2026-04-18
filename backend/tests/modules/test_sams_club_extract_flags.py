"""Regression guards on `containers/sams_club/extract.sh`.

Sam's Club gates the `/s/` search path by IP reputation: AWS datacenter IPs
get redirected to `/are-you-human?url=...` (Akamai-style interstitial). The
sams_club container routes ALL Chromium egress through Decodo's residential
proxy to defeat this — same architecture as fb_marketplace after the
SP-decodo-scoping fix (2026-04-17).

That routing makes every Chromium-internal background fetch (component
updates, autofill, safe-browsing, GCM, optimization-guide) consume paid
residential bytes unless it's either (a) explicitly disabled via the
telemetry kill flags below, or (b) listed in --proxy-bypass-list so it
egresses direct over the datacenter IP instead.

This test parses `extract.sh` as text and asserts the critical flags are
present. It cannot verify Chromium actually honors them at runtime — that's
a manual post-deploy check via `docker exec samsclub tail /tmp/proxy_bytes.log`
(see docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11).
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXTRACT_SH = (
    Path(__file__).resolve().parents[3]
    / "containers"
    / "sams_club"
    / "extract.sh"
)


@pytest.fixture(scope="module")
def extract_sh_text() -> str:
    assert EXTRACT_SH.is_file(), f"extract.sh not found at {EXTRACT_SH}"
    return EXTRACT_SH.read_text(encoding="utf-8")


# MARK: - Telemetry / background-networking kill flags

TELEMETRY_KILL_FLAGS = [
    "--disable-background-networking",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-pings",
    "--no-report-upload",
]


@pytest.mark.parametrize("flag", TELEMETRY_KILL_FLAGS)
def test_chromium_telemetry_flag_present(extract_sh_text: str, flag: str) -> None:
    assert flag in extract_sh_text, (
        f"Missing Chromium telemetry kill flag {flag!r} — without it, Chromium "
        "will burn Decodo residential-proxy bandwidth on background network "
        "requests unrelated to the scrape target. See §C.11."
    )


# MARK: - Feature-level disable flags (bundled into --disable-features=...)

FEATURE_DISABLES = [
    "OptimizationHints",
    "OptimizationGuideModelDownloading",
    "Translate",
    "MediaRouter",
    "AutofillServerCommunication",
]


@pytest.mark.parametrize("feature", FEATURE_DISABLES)
def test_chromium_feature_disabled(extract_sh_text: str, feature: str) -> None:
    assert feature in extract_sh_text, (
        f"Chromium feature {feature!r} must be listed in --disable-features=..."
    )


# MARK: - Proxy scoping


def test_proxy_bypass_list_defined(extract_sh_text: str) -> None:
    """The proxy-bypass list must exist so Chromium-internal fetches to
    google/gstatic/chromium-update hosts go out the datacenter IP direct,
    not through paid Decodo residential bytes."""
    assert "PROXY_BYPASS_LIST=" in extract_sh_text
    assert "--proxy-bypass-list" in extract_sh_text


@pytest.mark.parametrize(
    "pattern",
    [
        # `*.google.com` is the catch-all for accounts/mtalk/android.clients/
        # www/clients2/clients3 — Chromium's bypass glob doesn't support
        # mid-label wildcards like `clients*.google.com`, so we rely on the
        # leading-`*.` form which covers all subdomains at any depth.
        "*.google.com",
        "*.googleapis.com",
        "*.gvt1.com",
        "*.gstatic.com",
        "*.google-analytics.com",
        "*.googletagmanager.com",
        "*.doubleclick.net",
    ],
)
def test_proxy_bypass_list_includes_known_noise_domain(
    extract_sh_text: str, pattern: str
) -> None:
    assert pattern in extract_sh_text, (
        f"Decodo-cost noise domain {pattern!r} must be in PROXY_BYPASS_LIST"
    )


# MARK: - Image blocking (opt-out default-on)


def test_image_blocking_flag_is_configurable(extract_sh_text: str) -> None:
    """Default ON for bandwidth, but opt-out via SAMS_CLUB_DISABLE_IMAGES=0
    in case it ever breaks extraction."""
    assert "SAMS_CLUB_DISABLE_IMAGES" in extract_sh_text
    assert "imagesEnabled=false" in extract_sh_text


# MARK: - Bot-detection title regex


def test_bot_detection_matches_are_you_human(extract_sh_text: str) -> None:
    """Sam's Club's interstitial is titled 'Let us know you're not a robot'
    with URL `/are-you-human?...`. The existing `robot` regex catches the
    title; asserting `are you human` gives us a belt-and-suspenders check
    in case Samsclub ever flips to a title without 'robot' in it."""
    assert "are you human" in extract_sh_text.lower()


# MARK: - Homepage warmup is load-bearing


def test_homepage_warmup_is_present(extract_sh_text: str) -> None:
    """Even via Decodo, direct /s/ navigation without homepage cookies
    trips the /are-you-human/ gate. Keep the warmup."""
    assert 'ab open "$SITE_HOMEPAGE"' in extract_sh_text
