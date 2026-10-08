"""
WSS (encrypted WebSocket) server that streams GameEvent / MatchState JSON to the
phone Visualizer, in the formats of Section 6.2.3. Standalone test source: the
real system would push events produced by the AI pipeline instead.

Uses the same certificate as the ESP32 link (server.crt / server.key, made by
make_cert.py). The phone app must be allowed to trust that self-signed
certificate (see the notes at the bottom).

Works with the websockets 10.3 that is installed on the Ultra96 as well as newer
versions.

Usage:
    python3 game_event_wss_server.py [--port 8889] [--cert server.crt] [--key server.key]
                                     [--interval 1.5]
"""
import argparse
import asyncio
import itertools
import json
import logging
import random
import ssl
import sys
import time

import websockets

# LIVE EDIT HERE: edit readings/events, save, restart this Python server, then
# reconnect HTTPBot. Existing JSON field names and types stay unchanged.
DUMMY_GAME_EVENTS = [
    dict(source=1, target=2, punch='LEFT_HOOK', confidence=0.90, intensity=0.70),
    dict(source=2, target=1, punch='JAB', confidence=0.85, intensity=0.45),
    dict(source=1, target=2, punch='UPPERCUT', confidence=0.95, intensity=0.80),
    dict(source=2, target=1, punch='STRAIGHT', confidence=0.88, intensity=0.60),
]
DUMMY_MATCH_STATES = [
    dict(p1_health=100, p1_stamina=95, p2_health=90, p2_stamina=85, round_time=90),
    dict(p1_health=80, p1_stamina=70, p2_health=75, p2_stamina=65, round_time=60),
    dict(p1_health=60, p1_stamina=55, p2_health=50, p2_stamina=40, round_time=30),
]
COLOURS = ['\033[36m', '\033[33m', '\033[35m', '\033[32m']
RESET = '\033[0m'


def game_event_msg(seq, source, target, punch, confidence, intensity):
    return json.dumps({
        "seq": seq,
        "timestamp": int(time.time() * 1000),
        "event": "PUNCH",
        "source_player": source,
        "target_player": target,
        "punch": punch,
        "confidence": confidence,
        "intensity": intensity,
    })


def match_state_msg(seq, p1_health, p1_stamina, p2_health, p2_stamina, round_time):
    return json.dumps({
        "seq": seq,
        "timestamp": int(time.time() * 1000),
        "player_1": {"health": p1_health, "stamina": p1_stamina},
        "player_2": {"health": p2_health, "stamina": p2_stamina},
        "round_time": round_time,
        "state": "FIGHTING",
    })


def random_dummy_message(seq):
    """Alternate schema types; choose a random complete template within each.

    Sequence and timestamp are freshly generated for every transmitted JSON
    message. These independent snapshots are test data, not evolving game logic.
    """
    if seq % 2:
        return game_event_msg(seq, **random.choice(DUMMY_GAME_EVENTS))
    return match_state_msg(seq, **random.choice(DUMMY_MATCH_STATES))


def tls_description(websocket):
    """'TLSv1.3, TLS_AES_256_GCM_SHA384', or just 'TLS' if the library hides it."""
    try:
        obj = websocket.transport.get_extra_info('ssl_object')
        return f"{obj.version()}, {obj.cipher()[0]}"
    except Exception:
        return "TLS"


def make_handler(interval):
    connection_ids = itertools.count(1)
    async def handle_visualizer(websocket):
        addr = websocket.remote_address
        connection_id = next(connection_ids)
        colour = COLOURS[(connection_id - 1) % len(COLOURS)]
        tag = f'[PHONE {connection_id}]'
        print(f"{colour}{tag} connected {addr[0]}:{addr[1]} "
              f"({tls_description(websocket)}){RESET}", flush=True)

        seq = itertools.count(1)
        sent = 0
        try:
            while True:
                s = next(seq)
                msg = random_dummy_message(s)
                await websocket.send(msg)
                sent += 1
                # One readable line per message; separate colours per client.
                print(f"{colour}{tag} sent #{s}: {msg}{RESET}", flush=True)
                await asyncio.sleep(interval)
        except websockets.exceptions.ConnectionClosed:
            print(f"[DISCONNECTED] {addr[0]}:{addr[1]} after {sent} messages", flush=True)
    return handle_visualizer


def quiet_errors(loop, context):
    """If a TLS-related error does reach asyncio's error handler, print one readable
    line instead of a traceback.

    Note: a client that FAILS the TLS handshake (rejects our certificate, or speaks
    plain ws:// by mistake) is handled silently inside asyncio, so it does not show
    up here or anywhere on the server. If a phone cannot connect and this server
    printed no [NEW CONNECTION], the handshake failed: look at the phone's error."""
    exc = context.get('exception')
    text = str(exc) if exc else context.get('message', '')
    if isinstance(exc, (ssl.SSLError, ConnectionError, EOFError)) or 'SSL' in text or 'TLS' in text:
        print(f"[TLS] a client failed the handshake: {text.strip()[:110]}", flush=True)
        return
    loop.default_exception_handler(context)


async def main(args):
    if args.interval <= 0 or not DUMMY_GAME_EVENTS or not DUMMY_MATCH_STATES:
        sys.exit('interval must be positive and both dummy pools must be nonempty')
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
    except (FileNotFoundError, ssl.SSLError) as e:
        sys.exit(f"cannot start: {e}\n{args.cert} and {args.key} must exist (see make_cert.py)")

    asyncio.get_running_loop().set_exception_handler(quiet_errors)
    logging.getLogger('websockets').setLevel(logging.CRITICAL)   # we print our own one-liners

    print(f"WSS GameEvent server ready on port {args.port} (one message every {args.interval:g} s)", flush=True)
    async with websockets.serve(make_handler(args.interval), '0.0.0.0', args.port, ssl=ctx):
        await asyncio.Future()


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
# A self-signed certificate is not trusted by default, so the client has to be told
# to accept it:
#   - a WebSocket test app: turn on its "allow self-signed / ignore certificate errors" option
#   - Unity (ClientWebSocket): needs a certificate-validation callback that accepts our
#     certificate; the exact API depends on the Unity / .NET profile, so the Visualizer
#     team has to try it. Not verified here.
