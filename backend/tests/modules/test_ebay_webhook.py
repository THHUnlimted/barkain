"""Tests for the eBay Marketplace Account Deletion webhook.

5 tests:
- GET challenge returns the correct SHA-256 hash
- GET returns 503 when token is unset
- GET returns 503 when endpoint is unset
- POST logs and acks 204 on a well-formed payload
- POST acks 204 even when the body is not valid JSON
"""

import hashlib

import pytest

from app.config import settings

WEBHOOK_URL = "/api/v1/webhooks/ebay/account-deletion"
TOKEN = "barkain-ebay-webhook-token-xx-0123456789abcdef"
ENDPOINT = "https://api.barkain.app/api/v1/webhooks/ebay/account-deletion"


def _expected_hash(challenge_code: str) -> str:
    return hashlib.sha256(
        (challenge_code + TOKEN + ENDPOINT).encode("utf-8")
    ).hexdigest()


# MARK: - GET verification handshake


@pytest.mark.asyncio
async def test_get_returns_sha256_of_challenge_token_endpoint(client, monkeypatch):
    """eBay's handshake: SHA-256(challenge + token + endpoint) returned as hex."""
    monkeypatch.setattr(settings, "EBAY_VERIFICATION_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "EBAY_ACCOUNT_DELETION_ENDPOINT", ENDPOINT)

    challenge = "abc123challenge"
    response = await client.get(f"{WEBHOOK_URL}?challenge_code={challenge}")

    assert response.status_code == 200
    body = response.json()
    assert body == {"challengeResponse": _expected_hash(challenge)}


@pytest.mark.asyncio
async def test_get_returns_503_when_token_missing(client, monkeypatch):
    monkeypatch.setattr(settings, "EBAY_VERIFICATION_TOKEN", "")
    monkeypatch.setattr(settings, "EBAY_ACCOUNT_DELETION_ENDPOINT", ENDPOINT)

    response = await client.get(f"{WEBHOOK_URL}?challenge_code=anything")

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "EBAY_WEBHOOK_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_get_returns_503_when_endpoint_missing(client, monkeypatch):
    monkeypatch.setattr(settings, "EBAY_VERIFICATION_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "EBAY_ACCOUNT_DELETION_ENDPOINT", "")

    response = await client.get(f"{WEBHOOK_URL}?challenge_code=anything")

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "EBAY_WEBHOOK_NOT_CONFIGURED"


# MARK: - POST notification


@pytest.mark.asyncio
async def test_post_notification_returns_204(client):
    payload = {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
        "notification": {
            "notificationId": "n-1",
            "publishDate": "2026-04-17T00:00:00.000Z",
            "data": {
                "username": "testuser",
                "userId": "1234567890",
                "eoiUserId": "eoi-abc",
            },
        },
    }

    response = await client.post(WEBHOOK_URL, json=payload)

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_post_invalid_json_still_returns_204(client):
    """Swallow parse errors — non-2xx triggers eBay retries we don't want."""
    response = await client.post(
        WEBHOOK_URL,
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 204
