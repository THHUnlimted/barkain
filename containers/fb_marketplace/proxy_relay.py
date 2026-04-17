"""Local proxy relay for Decodo residential proxy authentication.

Chromium's --proxy-server flag only accepts host:port — it cannot pass
credentials inline. This relay accepts unauthenticated connections on
localhost:18080 and forwards through the Decodo proxy with credentials
injected via Proxy-Authorization header.

Why this exists: Facebook gates Marketplace access by IP reputation.
AWS datacenter IPs (AS14618) get a hard redirect to /login/. Decodo's
US residential IPs bypass this check — confirmed in 2i-d POC where
17 marketplace items rendered through Decodo vs 0 through EC2 direct.

Per-connection bandwidth accounting (SP-decodo-scoping, 2026-04-17): the
relay emits `proxy_bytes target=<host> up=<n> down=<n> total=<n> elapsed_ms=<n>`
on every connection close. grep+awk over `docker logs fbmarketplace` gives
per-target-host Decodo cost without scraping the Decodo dashboard. See
docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11.

Usage (inside the container):
    python3 /app/proxy_relay.py &
    chromium --proxy-server=http://127.0.0.1:18080 ...
"""

import asyncio
import base64
import os
import re
import sys
import time

# Per-connection accounting log. Persistent across extracts so post-mortem
# analysis works even though server.py captures (and discards on success)
# the extract.sh subprocess stderr. Tail with:
#   docker exec fbmarketplace tail -f /tmp/proxy_bytes.log
# Rotate: extract.sh may truncate on retailer container startup if needed;
# for now we let it grow (pennies of disk).
_BYTES_LOG = "/tmp/proxy_bytes.log"

UPSTREAM_HOST = os.environ.get("DECODO_PROXY_HOST", "gate.decodo.com")
UPSTREAM_PORT = int(os.environ.get("DECODO_PROXY_PORT", "7000"))
UPSTREAM_USER = os.environ.get("DECODO_PROXY_USER", "")
UPSTREAM_PASS = os.environ.get("DECODO_PROXY_PASS", "")
LISTEN_PORT = 18080

if UPSTREAM_USER and not UPSTREAM_USER.startswith("user-"):
    UPSTREAM_USER = f"user-{UPSTREAM_USER}"
if UPSTREAM_USER and "country-" not in UPSTREAM_USER:
    UPSTREAM_USER = f"{UPSTREAM_USER}-country-us"


# Accounting log format — keep the key order stable; downstream awk/grep
# scripts (docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11) depend on it.
_CONNECT_RE = re.compile(rb"^CONNECT\s+([^\s:]+)(?::\d+)?\s", re.IGNORECASE)
_HOST_RE = re.compile(rb"^Host:\s*([^\s:\r\n]+)", re.IGNORECASE | re.MULTILINE)


def _parse_target(header_block: bytes) -> str:
    """Extract the target hostname from a proxy request header block.

    HTTPS flows through CONNECT (host in request line); plain HTTP uses
    the Host: header. Falls back to 'unknown' if neither matches.
    """
    m = _CONNECT_RE.match(header_block)
    if m:
        return m.group(1).decode("ascii", errors="replace")
    m = _HOST_RE.search(header_block)
    if m:
        return m.group(1).decode("ascii", errors="replace")
    return "unknown"


class _ByteCounter:
    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = 0


async def _pipe(reader, writer, counter: _ByteCounter):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            counter.total += len(data)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(reader, writer):
    start = time.monotonic()
    up = _ByteCounter()
    down = _ByteCounter()
    target = "unknown"
    try:
        first_line = await asyncio.wait_for(reader.readline(), timeout=10)
        header_block = first_line
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            header_block += line
            if line in (b"\r\n", b"\n", b""):
                break

        target = _parse_target(header_block)
        # Account the client-side header bytes we already consumed — they
        # traveled client → relay but NOT relay → upstream (we rewrite
        # them), so they count as "up" from the client's perspective.
        up.total += len(header_block)

        creds = base64.b64encode(
            f"{UPSTREAM_USER}:{UPSTREAM_PASS}".encode()
        ).decode()
        auth_header = f"Proxy-Authorization: Basic {creds}\r\n".encode()

        parts = header_block.split(b"\r\n\r\n", 1)
        patched = parts[0] + b"\r\n" + auth_header + b"\r\n" + parts[1] if len(parts) > 1 else parts[0] + b"\r\n" + auth_header + b"\r\n"

        ur, uw = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
        uw.write(patched)
        await uw.drain()

        await asyncio.gather(_pipe(reader, uw, up), _pipe(ur, writer, down))
    except Exception as exc:
        print(f"relay: {exc}", file=sys.stderr)
    finally:
        try:
            writer.close()
        except Exception:
            pass
        elapsed_ms = int((time.monotonic() - start) * 1000)
        line = (
            f"proxy_bytes target={target} up={up.total} down={down.total} "
            f"total={up.total + down.total} elapsed_ms={elapsed_ms}"
        )
        print(line, file=sys.stderr, flush=True)
        try:
            with open(_BYTES_LOG, "a", encoding="utf-8") as f:
                f.write(f"{int(time.time())} {line}\n")
        except OSError:
            pass  # non-fatal; stderr still carries the line


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", LISTEN_PORT)
    print(f"proxy_relay: listening on 127.0.0.1:{LISTEN_PORT}", file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
