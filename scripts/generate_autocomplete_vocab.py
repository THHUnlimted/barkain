"""Barkain autocomplete vocabulary generator (Step 3d, expanded in Step 3o-A).

Sweeps Amazon's public autocomplete endpoint across an alphabet of
prefixes, dedupes, scores by frequency, and writes a single JSON file
consumed by the iOS ``AutocompleteService``.

The output ships in the app bundle. Regeneration is manual — re-run on
flagship launches or when the term-mix feels stale.

Step 3o-A removed the in-script electronics filter (``is_electronics``)
in favour of source-scope diversity. Six default Amazon scopes
(``aps``, ``electronics``, ``grocery``, ``pet-supplies``, ``tools``,
``beauty``) plus three probe-gated extras (``automotive``,
``health-personal-care``, ``office-products``) replace the
single-vertical bias documented in Discovery_Category_Expansion_v1.

Usage::

    python3 scripts/generate_autocomplete_vocab.py
    python3 scripts/generate_autocomplete_vocab.py --dry-run
    python3 scripts/generate_autocomplete_vocab.py \\
        --sources amazon_aps,amazon_electronics,amazon_grocery,amazon_pet-supplies,amazon_tools,amazon_beauty \\
        --prefix-depth 2 --throttle 1.0 --max-terms 15000 \\
        --output Barkain/Resources/autocomplete_vocab.json --resume

Sources:
    amazon_aps                   Amazon all departments     (default)
    amazon_electronics           Amazon electronics scope   (default)
    amazon_grocery               Amazon grocery scope       (default)
    amazon_pet-supplies          Amazon pet-supplies scope  (default)
    amazon_tools                 Amazon tools scope         (default)
    amazon_beauty                Amazon beauty scope        (default)
    amazon_automotive            Amazon automotive scope    (probe-gated)
    amazon_health-personal-care  Amazon HPC scope           (probe-gated)
    amazon_office-products       Amazon office scope        (probe-gated)
    bestbuy                      Best Buy autocomplete      (optional, skips on shape drift)
    ebay                         eBay autosug               (optional, skips on shape drift)

Exit codes:
    0  full success
    2  partial success (one or more sources failed)
    1  total failure (no terms produced)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import string
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "Barkain" / "Resources" / "autocomplete_vocab.json"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / ".autocomplete_cache"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("barkain.generate_autocomplete_vocab")

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15"
DEFAULT_SOURCES = (
    "amazon_aps",
    "amazon_electronics",
    "amazon_grocery",
    "amazon_pet-supplies",
    "amazon_tools",
    "amazon_beauty",
)
PROBE_SCOPE_CANDIDATES = (
    "amazon_automotive",
    "amazon_health-personal-care",
    "amazon_office-products",
)
PROBE_PREFIXES = ("ca", "pa", "tir")
PROBE_THRESHOLD = 5.0
ALL_SOURCES = (*DEFAULT_SOURCES, *PROBE_SCOPE_CANDIDATES, "bestbuy", "ebay")
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 0.5

# Test seam: monkeypatched in unit tests to avoid real sleeping.
_async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


# MARK: - Normalization & display casing

_PUNCT_STRIP = string.punctuation
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(term: str) -> str:
    """Lowercase, strip outer punctuation/whitespace, collapse internal spaces."""
    cleaned = term.strip().strip(_PUNCT_STRIP).strip()
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).lower()
    return cleaned


def display_case(normalized: str, preserve_upper: set[str]) -> str:
    """Return a display-friendly casing of ``normalized``.

    Tokens in ``preserve_upper`` (raw tokens that appeared all-uppercase
    in the source response and were ≤4 chars) keep their uppercase form;
    everything else is Title Cased.
    """
    out: list[str] = []
    for token in normalized.split():
        if token in preserve_upper:
            out.append(token.upper())
        else:
            out.append(token[:1].upper() + token[1:])
    return " ".join(out)


# MARK: - Prefix generation

def generate_prefixes(depth: int) -> list[str]:
    """Return depth-1 single chars + depth-2 pairs (a–z)."""
    if depth < 1:
        return []
    letters = string.ascii_lowercase
    out = list(letters)
    if depth >= 2:
        out.extend(a + b for a in letters for b in letters)
    return out


# MARK: - Source-specific HTTP fetchers

class SourceShapeError(Exception):
    """Raised when a non-required source returns an unparseable shape."""


async def _http_get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, str]
) -> httpx.Response:
    """GET with exponential back-off on 429/5xx + transient network errors."""
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = await client.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            await _async_sleep(BACKOFF_BASE_S * (2**attempt))
            continue
        if resp.status_code in RETRYABLE_STATUS:
            await _async_sleep(BACKOFF_BASE_S * (2**attempt))
            continue
        return resp
    if last_exc:
        raise last_exc
    return resp  # pragma: no cover — loop guarantees at least one iteration


def _parse_amazon(payload: dict) -> tuple[list[str], set[str]]:
    """Return (raw_values, all_uppercase_tokens) from an Amazon response."""
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list):
        raise SourceShapeError("amazon: missing 'suggestions' list")
    values: list[str] = []
    uppers: set[str] = set()
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        values.append(value)
        for tok in value.split():
            if 1 < len(tok) <= 4 and tok.isupper():
                uppers.add(tok.lower())
    return values, uppers


async def fetch_amazon(
    client: httpx.AsyncClient, source: str, prefix: str
) -> tuple[list[str], set[str]]:
    alias = source.removeprefix("amazon_")
    resp = await _http_get_with_retry(
        client,
        "https://completion.amazon.com/api/2017/suggestions",
        params={"mid": "ATVPDKIKX0DER", "alias": alias, "prefix": prefix},
    )
    if resp.status_code != 200:
        raise SourceShapeError(f"amazon: HTTP {resp.status_code}")
    return _parse_amazon(resp.json())


async def fetch_bestbuy(
    client: httpx.AsyncClient, source: str, prefix: str
) -> tuple[list[str], set[str]]:
    resp = await _http_get_with_retry(
        client,
        "https://www.bestbuy.com/autocomplete/searches",
        params={"q": prefix},
    )
    if resp.status_code != 200:
        raise SourceShapeError(f"bestbuy: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SourceShapeError("bestbuy: non-JSON response") from exc
    # Best Buy's shape is volatile; accept any list of {term: str} or {value: str}.
    items = payload if isinstance(payload, list) else payload.get("suggestions") or []
    if not isinstance(items, list):
        raise SourceShapeError("bestbuy: unexpected shape")
    values: list[str] = []
    for item in items:
        if isinstance(item, dict):
            v = item.get("term") or item.get("value")
        elif isinstance(item, str):
            v = item
        else:
            v = None
        if isinstance(v, str) and v.strip():
            values.append(v)
    return values, set()


async def fetch_ebay(
    client: httpx.AsyncClient, source: str, prefix: str
) -> tuple[list[str], set[str]]:
    resp = await _http_get_with_retry(
        client,
        "https://autosug.ebay.com/autosug",
        params={"kwd": prefix, "sId": "0", "_jgr": "1", "_ch": "0", "_help": "1"},
    )
    if resp.status_code != 200:
        raise SourceShapeError(f"ebay: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SourceShapeError("ebay: non-JSON response") from exc
    suggestions = (payload.get("res") or {}).get("sug") if isinstance(payload, dict) else None
    if not isinstance(suggestions, list):
        raise SourceShapeError("ebay: missing res.sug")
    return [s for s in suggestions if isinstance(s, str) and s.strip()], set()


SOURCE_FETCHERS: dict[
    str, Callable[[httpx.AsyncClient, str, str], Awaitable[tuple[list[str], set[str]]]]
] = {
    **{src: fetch_amazon for src in (*DEFAULT_SOURCES, *PROBE_SCOPE_CANDIDATES)},
    "bestbuy": fetch_bestbuy,
    "ebay": fetch_ebay,
}


# MARK: - Cache I/O

def _cache_path(cache_dir: Path, source: str, prefix: str) -> Path:
    return cache_dir / f"{source}_{prefix}.json"


def load_cached(cache_dir: Path, source: str, prefix: str) -> list[str] | None:
    path = _cache_path(cache_dir, source, prefix)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        return [v for v in data["values"] if isinstance(v, str)]
    return None


def write_cache(
    cache_dir: Path, source: str, prefix: str, values: list[str]
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(cache_dir, source, prefix).write_text(
        json.dumps({"values": values}, ensure_ascii=False), encoding="utf-8"
    )


# MARK: - Sweep orchestration

@dataclass
class SweepStats:
    total_prefixes_swept: int = 0
    raw_suggestions: int = 0
    after_dedup: int = 0
    sources_succeeded: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    scope_probes: dict[str, float] = field(default_factory=dict)
    scope_probes_admitted: list[str] = field(default_factory=list)


@dataclass
class TermAccumulator:
    """Tracks unique terms by normalized form, scoring + display casing."""

    occurrences: dict[str, set[str]] = field(default_factory=dict)
    """normalized -> set of (source, prefix) keys it appeared under"""

    raw_uppercase_tokens: set[str] = field(default_factory=set)

    def record(self, raw: str, source: str, prefix: str) -> None:
        normalized = normalize(raw)
        if not normalized:
            return
        self.occurrences.setdefault(normalized, set()).add(f"{source}|{prefix}")

    def add_uppercase_tokens(self, tokens: set[str]) -> None:
        self.raw_uppercase_tokens |= tokens


async def sweep_source(
    client: httpx.AsyncClient,
    source: str,
    prefixes: list[str],
    accumulator: TermAccumulator,
    stats: SweepStats,
    *,
    throttle: float,
    cache_dir: Path,
    resume: bool,
) -> bool:
    """Run one source over all prefixes. Returns True if at least one prefix succeeded."""
    fetcher = SOURCE_FETCHERS[source]
    semaphore = asyncio.Semaphore(1)
    any_success = False
    for prefix in prefixes:
        async with semaphore:
            cached: list[str] | None = None
            if resume:
                cached = load_cached(cache_dir, source, prefix)

            t0 = time.monotonic()
            if cached is not None:
                values, uppers = cached, set()
                cache_hit = True
            else:
                try:
                    values, uppers = await fetcher(client, source, prefix)
                except SourceShapeError as exc:
                    logger.warning("[%s] prefix=%s skipped: %s", source, prefix, exc)
                    await _async_sleep(throttle)
                    continue
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    logger.warning(
                        "[%s] prefix=%s network error after retries: %s",
                        source, prefix, exc,
                    )
                    await _async_sleep(throttle)
                    continue
                cache_hit = False
                write_cache(cache_dir, source, prefix, values)

            stats.total_prefixes_swept += 1
            stats.raw_suggestions += len(values)
            kept_local = 0
            accumulator.add_uppercase_tokens(uppers)
            for raw in values:
                accumulator.record(raw, source, prefix)
                kept_local += 1
            any_success = True
            elapsed = time.monotonic() - t0
            logger.info(
                "[%s] prefix=%s raw=%d cached=%s elapsed=%.2fs",
                source, prefix, len(values), str(cache_hit).lower(), elapsed,
            )
            if not cache_hit:
                await _async_sleep(throttle)
    return any_success


# MARK: - Probe-gated scope extras

async def probe_scope(
    client: httpx.AsyncClient,
    source: str,
    *,
    throttle: float,
    cache_dir: Path,
) -> float:
    """Hit ``PROBE_PREFIXES`` against ``source`` and return average yield.

    Caches each prefix so an admitted scope's main sweep starts warm.
    SourceShapeError or transport errors count as 0 suggestions for that
    prefix; the probe never raises.
    """
    fetcher = SOURCE_FETCHERS[source]
    yields: list[int] = []
    for prefix in PROBE_PREFIXES:
        try:
            values, _ = await fetcher(client, source, prefix)
        except SourceShapeError as exc:
            logger.warning("[probe %s] prefix=%s shape error: %s", source, prefix, exc)
            yields.append(0)
            await _async_sleep(throttle)
            continue
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("[probe %s] prefix=%s network error: %s", source, prefix, exc)
            yields.append(0)
            await _async_sleep(throttle)
            continue
        yields.append(len(values))
        write_cache(cache_dir, source, prefix, values)
        await _async_sleep(throttle)
    return sum(yields) / len(yields) if yields else 0.0


async def probe_extra_scopes(
    client: httpx.AsyncClient,
    candidates: tuple[str, ...],
    already_in_sweep: set[str],
    stats: SweepStats,
    *,
    throttle: float,
    cache_dir: Path,
) -> list[str]:
    """Probe each candidate not already in the sweep; return admitted scopes."""
    admitted: list[str] = []
    for candidate in candidates:
        if candidate in already_in_sweep:
            continue
        avg = await probe_scope(
            client, candidate, throttle=throttle, cache_dir=cache_dir
        )
        stats.scope_probes[candidate] = round(avg, 2)
        if avg >= PROBE_THRESHOLD:
            logger.info("scope=%s probe avg=%.1f admitted", candidate, avg)
            admitted.append(candidate)
        else:
            logger.info(
                "scope=%s probe avg=%.1f below threshold; skipping", candidate, avg
            )
    stats.scope_probes_admitted = list(admitted)
    return admitted


# MARK: - Parallel sweep orchestration

async def sweep_all_sources(
    client: httpx.AsyncClient,
    sources: list[str],
    prefixes: list[str],
    accumulator: TermAccumulator,
    stats: SweepStats,
    *,
    throttle: float,
    cache_dir: Path,
    resume: bool,
) -> dict[str, bool]:
    """Run every source's sweep concurrently.

    Per-source per-prefix throttle stays at 1.0s; the wall-clock win is
    cross-source. ``return_exceptions=True`` so a single source failing
    (Amazon retiring a scope alias mid-run, transient transport blow-up)
    doesn't kill the entire sweep — log + omit, continue.
    """
    tasks = [
        sweep_source(
            client, source, prefixes, accumulator, stats,
            throttle=throttle, cache_dir=cache_dir, resume=resume,
        )
        for source in sources
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, bool] = {}
    for source, result in zip(sources, results):
        if isinstance(result, BaseException):
            logger.warning("sweep_source failed for %s: %s", source, result)
            out[source] = False
        else:
            out[source] = bool(result)
    return out


# MARK: - Final assembly

def assemble_terms(
    accumulator: TermAccumulator,
    stats: SweepStats,
    *,
    max_terms: int,
) -> list[dict[str, object]]:
    stats.after_dedup = len(accumulator.occurrences)
    kept = [
        (normalized, len(occurrences))
        for normalized, occurrences in accumulator.occurrences.items()
    ]
    kept.sort(key=lambda pair: (-pair[1], pair[0]))
    limited = kept[:max_terms]
    return [
        {"t": display_case(normalized, accumulator.raw_uppercase_tokens), "s": score}
        for normalized, score in limited
    ]


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_output_payload(
    terms: list[dict[str, object]],
    stats: SweepStats,
    *,
    sources: list[str],
) -> dict[str, object]:
    return {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit(),
        "sources": sources,
        "stats": {
            "total_prefixes_swept": stats.total_prefixes_swept,
            "raw_suggestions": stats.raw_suggestions,
            "after_dedup": stats.after_dedup,
            "scope_probes": dict(stats.scope_probes),
            "scope_probes_admitted": list(stats.scope_probes_admitted),
        },
        "terms": terms,
    }


# MARK: - CLI

async def run(args: argparse.Namespace) -> int:
    sources: list[str] = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        logger.error("Unknown source(s): %s", ", ".join(unknown))
        return 1

    prefixes = generate_prefixes(args.prefix_depth)
    cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else DEFAULT_CACHE_DIR
    output_path = Path(args.output).resolve()

    accumulator = TermAccumulator()
    stats = SweepStats()

    timeout = httpx.Timeout(15.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        if not args.skip_probes:
            admitted = await probe_extra_scopes(
                client,
                PROBE_SCOPE_CANDIDATES,
                already_in_sweep=set(sources),
                stats=stats,
                throttle=args.throttle,
                cache_dir=cache_dir,
            )
            sources = sources + admitted

        outcomes = await sweep_all_sources(
            client,
            sources,
            prefixes,
            accumulator,
            stats,
            throttle=args.throttle,
            cache_dir=cache_dir,
            resume=args.resume,
        )

    for source, ok in outcomes.items():
        if ok:
            stats.sources_succeeded.append(source)
        else:
            stats.sources_failed.append(source)
            logger.error("source=%s produced no usable data", source)

    terms = assemble_terms(accumulator, stats, max_terms=args.max_terms)
    payload = build_output_payload(terms, stats, sources=sources)

    if args.dry_run:
        logger.info(
            "[dry-run] would write %d terms (raw=%d, dedup=%d) to %s",
            len(terms), stats.raw_suggestions, stats.after_dedup, output_path,
        )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        size_kb = output_path.stat().st_size / 1024
        logger.info(
            "wrote %d terms to %s (%.1f KB)", len(terms), output_path, size_kb
        )

    if not terms:
        return 1
    if stats.sources_failed:
        return 2
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Barkain autocomplete vocabulary JSON.",
    )
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help=(
            "Comma-separated source ids. Defaults to the 6-scope mix from Step 3o-A. "
            "Probe-gated extras (amazon_automotive, amazon_health-personal-care, "
            "amazon_office-products) are admitted automatically when their probe "
            "yield averages >= 5 suggestions/prefix."
        ),
    )
    parser.add_argument(
        "--prefix-depth", type=int, default=2,
        help="1=single chars (26), 2=add pairs (702 total)",
    )
    parser.add_argument(
        "--throttle", type=float, default=1.0,
        help="Seconds to sleep between requests within a single source (>=0).",
    )
    parser.add_argument(
        "--max-terms", type=int, default=15000,
        help="Cap on terms in the output JSON.",
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help="Path to write the vocab JSON.",
    )
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help="Directory for resume cache files.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip prefixes already in the cache directory.",
    )
    parser.add_argument(
        "--skip-probes", action="store_true",
        help="Skip probe-gated scope extras (probes run by default).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
