"""Local proxy relay for Decodo residential proxy authentication.

Chromium's --proxy-server flag only accepts host:port — it cannot pass
credentials inline. This relay accepts unauthenticated connections on
localhost:18080 and forwards through the Decodo proxy with credentials
injected via Proxy-Authorization header.

Why this exists: Facebook gates Marketplace access by IP reputation.
AWS datacenter IPs (AS14618) get a hard redirect to /login/. Decodo's
US residential IPs bypass this check — confirmed in 2i-d POC where
17 marketplace items rendered through Decodo vs 0 through EC2 direct.

Usage (inside the container):
    python3 /app/proxy_relay.py &
    chromium --proxy-server=http://127.0.0.1:18080 ...
"""

import asyncio
import base64
import os
import sys

UPSTREAM_HOST = os.environ.get("DECODO_PROXY_HOST", "gate.decodo.com")
UPSTREAM_PORT = int(os.environ.get("DECODO_PROXY_PORT", "7000"))
UPSTREAM_USER = os.environ.get("DECODO_PROXY_USER", "")
UPSTREAM_PASS = os.environ.get("DECODO_PROXY_PASS", "")
LISTEN_PORT = 18080

if UPSTREAM_USER and not UPSTREAM_USER.startswith("user-"):
    UPSTREAM_USER = f"user-{UPSTREAM_USER}"
if UPSTREAM_USER and "country-" not in UPSTREAM_USER:
    UPSTREAM_USER = f"{UPSTREAM_USER}-country-us"


async def _pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
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
    try:
        first_line = await asyncio.wait_for(reader.readline(), timeout=10)
        header_block = first_line
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            header_block += line
            if line in (b"\r\n", b"\n", b""):
                break

        creds = base64.b64encode(
            f"{UPSTREAM_USER}:{UPSTREAM_PASS}".encode()
        ).decode()
        auth_header = f"Proxy-Authorization: Basic {creds}\r\n".encode()

        parts = header_block.split(b"\r\n\r\n", 1)
        patched = parts[0] + b"\r\n" + auth_header + b"\r\n" + parts[1] if len(parts) > 1 else parts[0] + b"\r\n" + auth_header + b"\r\n"

        ur, uw = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
        uw.write(patched)
        await uw.drain()

        await asyncio.gather(_pipe(reader, uw), _pipe(ur, writer))
    except Exception as exc:
        print(f"relay: {exc}", file=sys.stderr)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", LISTEN_PORT)
    print(f"proxy_relay: listening on 127.0.0.1:{LISTEN_PORT}", file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
