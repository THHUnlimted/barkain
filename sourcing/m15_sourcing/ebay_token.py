"""eBay App Access Token — shared with M2 when available, standalone otherwise.

The sourcing adapter and ``m2_prices/adapters/ebay_browse_api`` use the *same*
App ID and the same 2 h ``client_credentials`` token. Two independent caches
would double the OAuth traffic for nothing and halve the effective TTL from the
perspective of eBay's rate accounting.

So: if the main backend is importable, we delegate to M2's cache outright. If
it isn't — the module is still isolated under ``sourcing/``, or it's running in
a standalone worker — we fall back to our own equivalent implementation.

The delegating path is the one that runs in production. The standalone path
exists so this package can be developed, tested and benchmarked before it's
wired into the app, which is the whole point of keeping it in one directory.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import quote_plus

import httpx

from m15_sourcing.config import SourcingSettings, settings as default_settings

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"
_REQUEST_TIMEOUT = 15
_TOKEN_REFRESH_BUFFER = 60  # refresh 60 s before expiry


class EbayBrowseNotConfiguredError(RuntimeError):
    """Raised when a token is requested without App ID + Cert ID set."""


def is_configured(cfg: SourcingSettings | None = None) -> bool:
    c = cfg or default_settings
    return bool(c.EBAY_APP_ID and c.EBAY_CERT_ID)


def _m2_token_module():
    """Return M2's Browse adapter if the main backend is on the path, else None."""
    try:
        from modules.m2_prices.adapters import ebay_browse_api  # type: ignore
    except ImportError:
        return None
    return ebay_browse_api


_token_cache: dict[str, float | str | None] = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


async def get_app_token(cfg: SourcingSettings | None = None) -> str:
    """Return a valid App Access Token, refreshing shortly before expiry."""
    c = cfg or default_settings

    shared = _m2_token_module()
    if shared is not None:
        # M2 owns the cache. Its Settings object carries the same credential
        # names, so its own default settings instance is the right one to use —
        # passing ours would bypass whatever the app has configured.
        return await shared._get_app_token(shared.default_settings)

    async with _token_lock:
        now = time.time()
        token = _token_cache.get("token")
        expires_at = float(_token_cache.get("expires_at") or 0.0)
        if token and expires_at > now + _TOKEN_REFRESH_BUFFER:
            return str(token)

        if not is_configured(c):
            raise EbayBrowseNotConfiguredError(
                "EBAY_APP_ID and EBAY_CERT_ID must both be set to use the Browse API"
            )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                _OAUTH_URL,
                auth=(c.EBAY_APP_ID, c.EBAY_CERT_ID),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=(
                    f"grant_type=client_credentials&scope={quote_plus(_OAUTH_SCOPE)}"
                ),
            )
        resp.raise_for_status()
        payload = resp.json()

        access_token = payload.get("access_token")
        if not access_token:
            raise EbayBrowseNotConfiguredError("eBay OAuth response carried no access_token")

        _token_cache["token"] = access_token
        _token_cache["expires_at"] = now + float(payload.get("expires_in", 7200))
        return str(access_token)
