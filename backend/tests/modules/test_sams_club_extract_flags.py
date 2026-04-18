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


# MARK: - Sams-Club-specific CDN bypass (bandwidth reduction 2026-04-18)


@pytest.mark.parametrize(
    "pattern",
    [
        # Image CDNs — not IP-gated. Biggest savings: ~700 KB/run measured.
        "*.samsclubimages.com",
        "*.walmartimages.com",
        # Fonts — not IP-gated.
        "*.typekit.net",
        # Ad viewability / session replay — not IP-gated, not load-bearing
        # for DOM extraction.
        "*.doubleverify.com",
        "*.quantummetric.com",
        "*.googlesyndication.com",
        "*.adtrafficquality.google",
        # Beacons — telemetry, not load-bearing.
        "*.crcldu.com",
        "*.wal.co",
    ],
)
def test_proxy_bypass_list_includes_cdn_domain(
    extract_sh_text: str, pattern: str
) -> None:
    """CDNs that aren't IP-gated must be in the bypass list so their bytes
    egress the datacenter IP direct instead of burning Decodo residential
    bandwidth. Verified safe 2026-04-18: the images/fonts/ads are unrelated
    to PerimeterX fingerprinting, which reads from *.px-cdn.net / px-cloud.net
    — those MUST stay on-proxy."""
    assert pattern in extract_sh_text, (
        f"CDN domain {pattern!r} must be in PROXY_BYPASS_LIST — otherwise "
        "it burns paid Decodo bytes despite not being IP-gated."
    )


@pytest.mark.parametrize(
    "hostname",
    [
        # First-party subdomains that serve analytics/images but aren't
        # IP-gated. Chromium's bypass glob requires explicit hostnames here
        # because a parent `*.samsclub.com` would also match the main site.
        "beacon.samsclub.com",
        "dap.samsclub.com",
        "titan.samsclub.com",
        "scene7.samsclub.com",
        "dapglass.samsclub.com",
    ],
)
def test_first_party_telemetry_subdomain_bypassed(
    extract_sh_text: str, hostname: str
) -> None:
    """Sam's Club first-party telemetry/image subdomains are not IP-gated
    (only px-cdn.net / px-cloud.net are). Bypassing them off Decodo saves
    ~1.7 MB/run — measured 2026-04-18."""
    assert hostname in extract_sh_text, (
        f"First-party telemetry subdomain {hostname!r} must be in "
        "PROXY_BYPASS_LIST — leaving it on-proxy burns Decodo bytes with "
        "no IP-reputation benefit."
    )


def test_perimeterx_is_not_bypassed(extract_sh_text: str) -> None:
    """PerimeterX MUST stay on the Decodo proxy — it's the retailer's
    IP-reputation check. If px-cdn.net or px-cloud.net were in the bypass
    list, PX would see a datacenter IP for telemetry while the HTML fetch
    used a residential IP, and it'd fire the bot gate."""
    bypass_block = extract_sh_text.split("PROXY_BYPASS_LIST=", 1)[1].split("\n", 1)[0]
    assert "px-cdn.net" not in bypass_block, (
        "px-cdn.net MUST stay on-proxy — it's the PerimeterX IP checkpoint"
    )
    assert "px-cloud.net" not in bypass_block, (
        "px-cloud.net MUST stay on-proxy — it's the PerimeterX IP checkpoint"
    )


def test_samsclub_main_site_not_bypassed(extract_sh_text: str) -> None:
    """The site itself must stay on-proxy — that's the whole point of using
    Decodo."""
    bypass_block = extract_sh_text.split("PROXY_BYPASS_LIST=", 1)[1].split("\n", 1)[0]
    # We bypass *.samsclubimages.com but not the main *.samsclub.com.
    assert "*.samsclub.com" not in bypass_block, (
        "*.samsclub.com MUST stay on-proxy — the site is IP-gated"
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
