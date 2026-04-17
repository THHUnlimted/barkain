"""eBay Marketplace Account Deletion webhook.

eBay requires every app with production API access to expose a public HTTPS
endpoint that (a) answers a GET verification handshake and (b) accepts POST
deletion notifications. Without this endpoint + matching dashboard config,
Browse API production keys are blocked.

## Handshake (GET)

eBay hits the endpoint with ``?challenge_code=<random>``. We compute
``SHA-256(challenge_code + verification_token + endpoint_url)`` as a lowercase
hex digest and return ``{"challengeResponse": "<hex>"}`` with HTTP 200.

The ``verification_token`` is an opaque 32-80 char string we pick and paste
into the eBay developer portal. The ``endpoint_url`` is the fully-qualified
public HTTPS URL (``https://api.barkain.app/api/v1/webhooks/ebay/account-deletion``
or whatever stable DNS we put in front of the backend). Both must match
between ``settings`` and the portal exactly — trailing slashes, casing,
scheme. Any drift and the hash doesn't match, eBay rejects the endpoint.

## Notification (POST)

eBay POSTs a JSON payload when a user deletes their account:

    {
      "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION", ...},
      "notification": {
        "notificationId": "...",
        "data": {"username": "...", "userId": "...", "eoiUserId": "..."}
      }
    }

We log and ack with 204. Barkain does not store per-user eBay data today
(we only consume public listings), so compliance is satisfied by the ack.
If future work caches user-specific eBay data, extend ``_handle_notification``
to purge by ``userId``/``eoiUserId``.
"""

import hashlib
import logging

from fastapi import APIRouter, Query, Request, Response

from app.config import settings
from app.errors import raise_http_error

logger = logging.getLogger("barkain.ebay_webhook")

router = APIRouter(prefix="/api/v1/webhooks/ebay", tags=["ebay-webhook"])


@router.get("/account-deletion")
async def verify_endpoint(
    challenge_code: str = Query(..., min_length=1, max_length=200),
) -> dict:
    """Answer eBay's verification GET by returning the expected SHA-256 hash."""
    token = settings.EBAY_VERIFICATION_TOKEN
    endpoint = settings.EBAY_ACCOUNT_DELETION_ENDPOINT
    if not token or not endpoint:
        logger.error(
            "eBay webhook verification attempted but EBAY_VERIFICATION_TOKEN "
            "or EBAY_ACCOUNT_DELETION_ENDPOINT is unset"
        )
        raise_http_error(
            status_code=503,
            code="EBAY_WEBHOOK_NOT_CONFIGURED",
            message="eBay webhook is not configured",
        )

    digest = hashlib.sha256(
        (challenge_code + token + endpoint).encode("utf-8")
    ).hexdigest()
    return {"challengeResponse": digest}


@router.post("/account-deletion", status_code=204)
async def receive_notification(request: Request) -> Response:
    """Log the deletion notification and ack with 204.

    We don't store eBay user data today, so a log+ack is compliant. Any
    exception is swallowed (logged at error level) because eBay retries on
    non-2xx and we'd rather burn the retry than wedge the pipeline on a
    malformed payload.
    """
    try:
        payload = await request.json()
    except Exception:
        logger.exception("eBay account-deletion POST had no valid JSON body")
        return Response(status_code=204)

    notification = (payload or {}).get("notification") or {}
    data = notification.get("data") or {}
    logger.info(
        "ebay.account_deletion notificationId=%s userId=%s eoiUserId=%s",
        notification.get("notificationId"),
        data.get("userId"),
        data.get("eoiUserId"),
    )
    return Response(status_code=204)
