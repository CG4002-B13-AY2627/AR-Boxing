"""Strict-TLS two-player smoke test against a running Ultra96 WSS endpoint."""

import argparse
import asyncio
import json
import ssl

import websockets


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


async def main(args):
    context = ssl.create_default_context(cafile=args.ca)
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
    print("WSS handshake passed: TLS verified, P1/P2 joined, occupied slot rejected, P1 reconnected")
    print(f"match={welcome_one['match_id']} stream={welcome_one['stream_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="wss://127.0.0.1:8889")
    parser.add_argument("--ca", help="trusted demo CA PEM; omit to use the OS trust store")
    asyncio.run(main(parser.parse_args()))
