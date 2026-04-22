#!/usr/bin/env python3
"""Resolve Facebook Marketplace numeric location IDs for real cities.

Runs two strategies per city and reports which one won + how long it took:

  B: GET /marketplace/<slug>/ without following redirects, read the Location
     header. Fastest (~100–300 ms), no rate limit, but only works when FB
     accepts the slug.
  A: POST to html.duckduckgo.com with "facebook marketplace <city> <state>"
     and grep the first facebook.com/marketplace/<id>/ URL out of the result
     page. Slower (~400–800 ms) and rate-limited (~30 req/min/IP) but handles
     everything Option B misses.

Nothing is persisted. This is a pre-wire sanity check to prove the resolver
approach works from Mike's LAN before we touch Postgres / iOS / the container.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_FB_ID_IN_URL = re.compile(r"/marketplace/(\d+)/")


def _load_env(path: Path) -> None:
    """Tiny .env loader — we don't want python-dotenv just for one script."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(Path(__file__).resolve().parent.parent / "backend" / ".env")


def _proxy_url() -> str | None:
    """Mirror `walmart_http._build_proxy_url`'s username + password encoding."""
    from urllib.parse import quote_plus

    user = os.environ.get("DECODO_PROXY_USER")
    pw = os.environ.get("DECODO_PROXY_PASS")
    host = os.environ.get("DECODO_PROXY_HOST", "gate.decodo.com")
    port = os.environ.get("DECODO_PROXY_PORT", "7000")
    if not (user and pw):
        return None
    # Decodo username must be "user-<name>-country-us" for US residential egress.
    if not user.startswith("user-"):
        user = f"user-{user}"
    if "country-" not in user:
        user = f"{user}-country-us"
    encoded_pass = quote_plus(pw)
    host_str = host if ":" in host else f"{host}:{port}"
    return f"http://{user}:{encoded_pass}@{host_str}"


def slug_variants(city: str) -> list[str]:
    """FB has accepted all three shapes for multi-word cities at various points."""
    c = city.lower().strip()
    return list(dict.fromkeys([
        c.replace(" ", ""),
        c.replace(" ", "-"),
        c.replace(" ", "_"),
    ]))


def try_slug_redirect(slug: str, client: httpx.Client) -> str | None:
    url = f"https://www.facebook.com/marketplace/{slug}/"
    try:
        r = client.get(
            url,
            headers={"User-Agent": UA},
            follow_redirects=False,
            timeout=10.0,
        )
    except httpx.RequestError:
        return None

    # Direct 301/302 with Location header — the clean path.
    if r.status_code in (301, 302):
        loc = r.headers.get("location", "")
        if m := _FB_ID_IN_URL.search(loc):
            return m.group(1)

    # FB sometimes serves 200 with the canonical numeric URL in the body.
    if r.status_code == 200:
        if m := _FB_ID_IN_URL.search(r.text):
            return m.group(1)

    return None


def try_ddg(city: str, state: str, client: httpx.Client) -> str | None:
    q = f"facebook marketplace {city} {state}"
    try:
        r = client.post(
            "https://html.duckduckgo.com/html/",
            headers={"User-Agent": UA},
            data={"q": q},
            timeout=15.0,
        )
    except httpx.RequestError:
        return None
    if r.status_code != 200:
        return None
    # First match is almost always the top organic result, which is the city page.
    if m := _FB_ID_IN_URL.search(r.text):
        return m.group(1)
    return None


@dataclass
class Result:
    city: str
    state: str
    location_id: str | None
    method: str
    elapsed_ms: int


def resolve(city: str, state: str, client: httpx.Client) -> Result:
    start = time.perf_counter()
    for slug in slug_variants(city):
        if lid := try_slug_redirect(slug, client):
            return Result(city, state, lid, f"slug:{slug}", int((time.perf_counter() - start) * 1000))
    if lid := try_ddg(city, state, client):
        return Result(city, state, lid, "ddg", int((time.perf_counter() - start) * 1000))
    return Result(city, state, None, "FAILED", int((time.perf_counter() - start) * 1000))


# Cities picked to exercise every failure mode we've seen, plus a batch of
# genuinely obscure small towns to stress-test the long tail.
TESTS: list[tuple[str, str]] = [
    # NYC boroughs — the original report; "brooklyn" slug used to silently
    # redirect to the generic category page and IP-geolocate to California.
    ("Brooklyn", "NY"),
    ("Manhattan", "NY"),
    ("Queens", "NY"),
    # Atlanta metro — the user's real test case in the field.
    ("Mableton", "GA"),
    ("Marietta", "GA"),
    ("Sandy Springs", "GA"),
    # LA metro
    ("Santa Monica", "CA"),
    ("Long Beach", "CA"),
    # Slugs that already worked in the old system — sanity check we didn't
    # break the easy path.
    ("Austin", "TX"),
    ("Seattle", "WA"),
    ("San Francisco", "CA"),
    # Small towns from the findings doc — known to resolve via DDG.
    ("Minco", "OK"),
    ("Norman", "OK"),
    # Obscure towns — anyone of these might have a neighbor with no FB page,
    # or a page that answers to a weird slug. Good long-tail stress.
    ("Barrow", "AK"),              # population ~4k, remote Arctic
    ("Truth or Consequences", "NM"),  # ambiguous name, 6k people
    ("Why", "AZ"),                 # 116 people, single-word town
    ("Pie Town", "NM"),            # ~200 people
    ("Cut and Shoot", "TX"),       # 1.2k, multi-word weird slug
    ("Gnaw Bone", "IN"),           # unincorporated, ~200
    ("Boring", "OR"),              # 8k, single-word easy
    ("Accident", "MD"),            # 300 people
    ("Embarrass", "MN"),           # 550 people
]


def main() -> None:
    proxy = _proxy_url()
    if proxy:
        print("Routing via Decodo residential proxy.")
    else:
        print("No DECODO_PROXY_USER/PASS found — running direct (expect FB 400 / DDG 202).")
    print(f"{'City':<22} {'State':<4} {'Method':<22} {'Location ID':<18} {'Time':>7}")
    print("-" * 80)
    proxies = proxy if proxy else None
    with httpx.Client(proxy=proxies, trust_env=False) as client:
        for city, state in TESTS:
            result = resolve(city, state, client)
            lid = result.location_id or "— FAILED —"
            print(
                f"{result.city:<22} {result.state:<4} {result.method:<22} "
                f"{lid:<18} {result.elapsed_ms:>5} ms"
            )
            # Gentle pacing so DDG doesn't flag us even on residential IPs.
            time.sleep(1.2)


if __name__ == "__main__":
    main()
