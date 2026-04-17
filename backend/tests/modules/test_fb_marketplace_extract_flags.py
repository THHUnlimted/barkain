"""Regression guards on `containers/fb_marketplace/extract.sh`.

The fb_marketplace container routes ALL Chromium egress through Decodo's
residential proxy (Facebook blocks AWS datacenter IPs at /login/). That makes
every Chromium background fetch — component updates, autofill suggestions,
safe-browsing pings, GCM, optimization-guide model downloads — consume paid
residential bytes. Without the flags asserted here, observed cost on the
Decodo dashboard was ~15 MB/hour of "Google domains" per container on top
of the legitimate facebook.com scraping traffic.

This test parses `extract.sh` as text and asserts the critical flags are
present. It cannot verify Chromium actually honors them at runtime — that's
a manual post-deploy check (see docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11).
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXTRACT_SH = (
    Path(__file__).resolve().parents[3]
    / "containers"
    / "fb_marketplace"
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
    """Default ON for bandwidth, but opt-out via FB_MARKETPLACE_DISABLE_IMAGES=0
    in case it ever breaks extraction."""
    assert "FB_MARKETPLACE_DISABLE_IMAGES" in extract_sh_text
    assert "imagesEnabled=false" in extract_sh_text
