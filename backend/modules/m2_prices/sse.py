"""Server-Sent Events (SSE) helpers for M2 price streaming.

Format per the W3C SSE spec:

    event: <event_type>
    data: <json-encoded payload>
    <blank line>

Consumers split on blank lines, then parse `event:` and `data:` prefixes.
"""

import json

from modules.m2_prices.service import _json_serializer

# Response headers for SSE endpoints. `X-Accel-Buffering: no` tells nginx to
# forward bytes immediately instead of buffering the response. `Cache-Control`
# keeps intermediaries from caching the stream. `Connection: keep-alive` keeps
# the TCP connection open for the duration of the stream.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def sse_event(event: str, data: dict) -> str:
    """Format a single SSE event as a wire-protocol string."""
    payload = json.dumps(data, default=_json_serializer)
    return f"event: {event}\ndata: {payload}\n\n"
