"""Two-player smoke test, or a scripted stand-in phone, for a running Ultra96 server.

Handshake check (default): P1/P2 join, an occupied slot is rejected, P1 reconnects.

    python smoke_test_visualizer_wss.py --url wss://192.168.137.1:8889 --ca ca.crt

Follow mode: act as one phone for the whole match, so a single Unity Editor
can play against it. It presses Ready / I'm set / Resume whenever its slot
isn't ready yet (including Play again after a match), and answers every PunchAttempt with TARGET_TRACKED.

    python smoke_test_visualizer_wss.py --url ws://127.0.0.1:8889 --follow 2
"""

import argparse
import asyncio
import itertools
import json
import ssl
import time

import websockets


# The command that makes this phone "done" with each phase.
# MATCH_END: "Play again" (RESTART), so a match can follow the result.
PHASE_COMMAND = {"LOBBY": "READY", "CALIBRATING": "CALIBRATED", "PAUSED": "RESUME",
                 "MATCH_END": "RESTART"}
RESEND_SECONDS = 2.0


def tls_for(url, ca):
    return ssl.create_default_context(cafile=ca) if url.startswith("wss://") else None


async def join(url, context, client_id, player_id):
    websocket = await websockets.connect(url, ssl=context)
    await websocket.send(json.dumps({
        "type": "ClientHello", "protocol_version": 2,
        "client_id": client_id, "player_id": player_id,
    }))
    welcome = json.loads(await asyncio.wait_for(websocket.recv(), 5))
    state = json.loads(await asyncio.wait_for(websocket.recv(), 5))
    if welcome.get("type") != "ServerWelcome" or welcome.get("player_id") != player_id:
        raise AssertionError(f"wrong P{player_id} welcome: {welcome}")
    if state.get("type") != "MatchState" or state.get("stream_id") != welcome["stream_id"]:
        raise AssertionError(f"missing or mismatched initial state: {state}")
    return websocket, welcome


async def handshake(args):
    context = tls_for(args.url, args.ca)
    one, welcome_one = await join(args.url, context, "wss-smoke-p1", 1)
    async with one:
        two, welcome_two = await join(args.url, context, "wss-smoke-p2", 2)
        async with two:
            if welcome_one["match_id"] != welcome_two["match_id"]:
                raise AssertionError("P1 and P2 joined different matches")
            async with websockets.connect(args.url, ssl=context) as duplicate:
                await duplicate.send(json.dumps({
                    "type": "ClientHello", "protocol_version": 2,
                    "client_id": "wss-smoke-intruder", "player_id": 1,
                }))
                try:
                    await asyncio.wait_for(duplicate.recv(), 5)
                except websockets.exceptions.ConnectionClosed as closed:
                    if closed.rcvd is None or closed.rcvd.code != 1008:
                        raise AssertionError("duplicate was not rejected with 1008")
                else:
                    raise AssertionError("duplicate P1 was accepted")

    await asyncio.sleep(0.1)
    again, welcome_again = await join(args.url, context, "wss-smoke-p1", 1)
    await again.close()
    if welcome_again["stream_id"] != welcome_one["stream_id"]:
        raise AssertionError("unexpected stream change during reconnect")
    secure = "TLS verified" if context else "plain ws (local)"
    print(f"Handshake passed: {secure}, P1/P2 joined, occupied slot rejected, P1 reconnected")
    print(f"match={welcome_one['match_id']} stream={welcome_one['stream_id']}")


async def follow(args):
    player = args.follow
    websocket, welcome = await join(args.url, tls_for(args.url, args.ca),
                                    f"follow-p{player}", player)
    print(f"[FOLLOW] P{player} joined stream={welcome['stream_id']} "
          f"commands={'yes' if welcome.get('supports_player_commands') else 'no'}", flush=True)
    ids = itertools.count(1)
    phase, sent_at = None, 0.0
    async with websocket:
        async for raw in websocket:
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "PunchAttempt":
                await websocket.send(json.dumps({
                    "type": "PunchObservation", "protocol_version": 2,
                    "match_id": message["match_id"], "stream_id": message["stream_id"],
                    "attack_id": message["attack_id"], "observer_player": player,
                    "observation": "TARGET_TRACKED", "target_age_ms": 0,
                    "client_timestamp": int(time.time() * 1000),
                }))
                print(f"[FOLLOW] answered {message['punch']} attempt: TARGET_TRACKED", flush=True)
            elif kind == "GameEvent" and message.get("event") == "PUNCH":
                print(f"[FOLLOW] P{message['source_player']} {message['punch']} "
                      f"{message['outcome']} {message['damage']:g}", flush=True)
            elif kind == "MatchState":
                me = message[f"player_{player}"]
                if message["state"] != phase:
                    phase, sent_at = message["state"], 0.0
                    print(f"[FOLLOW] {phase}  P1 HP={message['player_1']['health']:g} "
                          f"P2 HP={message['player_2']['health']:g} "
                          f"result={message.get('match_result', 'PENDING')}", flush=True)
                command = PHASE_COMMAND.get(phase)
                if (command and welcome.get("supports_player_commands") and
                        not me.get("ready") and time.monotonic() - sent_at > RESEND_SECONDS):
                    sent_at = time.monotonic()
                    await websocket.send(json.dumps({
                        "type": "PlayerCommand", "protocol_version": 2,
                        "match_id": message["match_id"], "stream_id": message["stream_id"],
                        "player_id": player, "command_id": f"follow-p{player}-{next(ids)}",
                        "command": command, "timestamp": int(time.time() * 1000),
                    }))
                    print(f"[FOLLOW] sent {command}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="wss://127.0.0.1:8889")
    parser.add_argument("--ca", help="trusted demo CA PEM; omit to use the OS trust store")
    parser.add_argument("--follow", type=int, choices=(1, 2),
                        help="play as this slot until the server closes (Ctrl+C to stop)")
    arguments = parser.parse_args()
    try:
        asyncio.run(follow(arguments) if arguments.follow else handshake(arguments))
    except KeyboardInterrupt:
        pass
