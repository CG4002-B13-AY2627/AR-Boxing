"""
Standalone protocol-v2 WSS transport demo for the phone Visualizer. Synthetic
punches use the shared server-side GameEngine; sensor/FPGA input is not wired.

Use a phone-facing certificate whose CA is explicitly trusted by iOS and whose
SAN matches the URL host (see ../Laptop/make_visualizer_cert.py). Copying a
certificate into Unity Assets does not establish OS trust.

Uses APIs present in websockets 10.3; verify on the deployed Ultra96.

Usage:
    python3 game_event_wss_server.py [--port 8889] [--cert server.crt] [--key server.key]
                                     [--interval 1.5]
"""
import argparse
import asyncio
import logging
import random
import ssl
import sys

import websockets
from visualizer_protocol import MAX_MESSAGE_BYTES, PhoneHub

# These are synthetic punch inputs; the demo hub resolves their outcomes.
DUMMY_GAME_EVENTS = [
    dict(source=1, target=2, punch='LEFT_HOOK', confidence=0.90, intensity=0.70),
    dict(source=2, target=1, punch='JAB', confidence=0.85, intensity=0.45),
    dict(source=1, target=2, punch='LEFT_UPPERCUT', confidence=0.95, intensity=0.80),
    dict(source=2, target=1, punch='CROSS', confidence=0.88, intensity=0.60),
]
def tls_description(websocket):
    """'TLSv1.3, TLS_AES_256_GCM_SHA384', or just 'TLS' if the library hides it."""
    try:
        obj = websocket.transport.get_extra_info('ssl_object')
        return f"{obj.version()}, {obj.cipher()[0]}"
    except Exception:
        return "TLS"


def make_handler(hub):
    async def handle_visualizer(websocket):
        addr = websocket.remote_address
        print(f"[PHONE] encrypted socket {addr[0]}:{addr[1]} "
              f"({tls_description(websocket)}); awaiting ClientHello", flush=True)
        try:
            await hub.handle(websocket)
        finally:
            print(f"[PHONE] disconnected {addr[0]}:{addr[1]}", flush=True)
    return handle_visualizer


async def stream_demo(hub, interval):
    while True:
        await asyncio.sleep(interval)
        if hub.engine.phase != "FIGHTING":
            continue
        choice = random.choice(DUMMY_GAME_EVENTS)
        await hub.request_punch(
            choice['source'], choice['punch'],
            choice['confidence'], choice['intensity'],
        )


def quiet_errors(loop, context):
    """If a TLS-related error does reach asyncio's error handler, print one readable
    line instead of a traceback.

    Note: a client that FAILS the TLS handshake (rejects our certificate, or speaks
    plain ws:// by mistake) is handled silently inside asyncio, so it does not show
    up here or anywhere on the server. If a phone cannot connect and this server
    printed no [PHONE] line, the TLS handshake likely failed: inspect the
    phone's connection error."""
    exc = context.get('exception')
    text = str(exc) if exc else context.get('message', '')
    if isinstance(exc, (ssl.SSLError, ConnectionError, EOFError)) or 'SSL' in text or 'TLS' in text:
        print(f"[TLS] a client failed the handshake: {text.strip()[:110]}", flush=True)
        return
    loop.default_exception_handler(context)


async def main(args):
    if args.interval <= 0 or not DUMMY_GAME_EVENTS:
        sys.exit('interval must be positive and the dummy punch pool nonempty')
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.cert, args.key)
    except (FileNotFoundError, ssl.SSLError) as e:
        sys.exit(f"cannot start: {e}\n{args.cert} and {args.key} must exist (see make_cert.py)")

    asyncio.get_running_loop().set_exception_handler(quiet_errors)
    logging.getLogger('websockets').setLevel(logging.WARNING)
    hub = PhoneHub()
    print(f"WSS protocol-v2 demo ready on port {args.port}, stream={hub.stream_id}", flush=True)
    async with websockets.serve(
        make_handler(hub), '0.0.0.0', args.port, ssl=ctx,
        max_size=MAX_MESSAGE_BYTES,
    ):
        await stream_demo(hub, args.interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8889)
    ap.add_argument('--cert', default='server.crt')
    ap.add_argument('--key', default='server.key')
    ap.add_argument('--interval', type=float, default=1.5, help='seconds between messages')
    args = ap.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)

# Notes for the phone side
# ------------------------
# Connect to  wss://<laptop hotspot IP>:8889  (the SSH tunnel must forward port 8889).
# A self-signed certificate needs explicit OS-level trust on the iPhone.
# Do not disable certificate or hostname validation in the Unity client.
