"""Protocol-v2 phone handshake and demo transport shared by both WSS servers.

This module is a transport fixture, not the authoritative boxing Game Engine.
Its demo punch events are explicitly zero-damage misses until the real engine
supplies resolved outcomes and state.
"""

import asyncio
import json
import re
import time
import uuid

import websockets


PROTOCOL_VERSION = 2
MAX_MESSAGE_BYTES = 65536
HELLO_TIMEOUT_SECONDS = 5
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
PUNCHES = frozenset((
    "JAB", "CROSS", "LEFT_HOOK", "RIGHT_HOOK",
    "LEFT_UPPERCUT", "RIGHT_UPPERCUT",
))


def decode_hello(raw):
    """Return (client_id, player_id), or None for a noncanonical ClientHello."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        message = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(message, dict) or set(message) != {
        "type", "protocol_version", "client_id", "player_id"
    }:
        return None
    client_id = message["client_id"]
    player_id = message["player_id"]
    if (message["type"] != "ClientHello" or
            type(message["protocol_version"]) is not int or
            message["protocol_version"] != PROTOCOL_VERSION or
            not isinstance(client_id, str) or not IDENTIFIER.fullmatch(client_id) or
            type(player_id) is not int or player_id not in (1, 2)):
        return None
    return client_id, player_id


def encode(message):
    return json.dumps(message, separators=(",", ":"), allow_nan=False)


class PhoneHub:
    """Two-player WSS demo hub; first claimant owns a slot for this process."""

    def __init__(self, match_id="match-demo-001"):
        self.match_id = match_id
        self.stream_id = "ultra96-" + uuid.uuid4().hex[:16]
        self.owners = {}             # player_id -> stable client_id
        self.active = {}             # player_id -> socket, including joining
        self.ready = {}              # player_id -> socket, after welcome/state
        self.event_seq = 0
        self.state_seq = 0

    def claim(self, client_id, player_id, websocket):
        if (player_id in self.active or
                (player_id in self.owners and self.owners[player_id] != client_id)):
            return False
        previous = next(
            (slot for slot, owner in self.owners.items() if owner == client_id), None
        )
        if previous is not None and previous != player_id:
            if previous in self.active:
                return False
            del self.owners[previous]
        self.owners[player_id] = client_id
        self.active[player_id] = websocket
        return True

    def release(self, player_id, websocket):
        if self.active.get(player_id) is websocket:
            del self.active[player_id]
        if self.ready.get(player_id) is websocket:
            del self.ready[player_id]

    def welcome(self, player_id):
        return {
            "type": "ServerWelcome", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "player_id": player_id, "server_timestamp": int(time.time() * 1000),
            "heartbeat_interval_ms": 5000,
        }

    def state(self):
        self.state_seq += 1
        player = {
            "health": 100.0, "stamina": 100.0, "is_blocking": False,
            "attack_multiplier": 1.0,
            "attack_multiplier_remaining_ms": 0,
        }
        return {
            "type": "MatchState", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "seq": self.state_seq, "timestamp": int(time.time() * 1000),
            "player_1": player.copy(), "player_2": player.copy(),
            "round_time": 90.0, "state": "FIGHTING", "active_items": [],
        }

    def demo_punch(self, source_player, punch, confidence, intensity):
        if source_player not in (1, 2) or punch not in PUNCHES:
            raise ValueError("invalid demo punch or player")
        if not (0 <= confidence <= 1 and 0 <= intensity <= 1):
            raise ValueError("invalid demo confidence or intensity")
        self.event_seq += 1
        return {
            "type": "GameEvent", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "seq": self.event_seq, "timestamp": int(time.time() * 1000),
            "event": "PUNCH", "source_player": source_player,
            "target_player": 3 - source_player, "punch": punch,
            "confidence": confidence, "intensity": intensity,
            "outcome": "MISS", "damage": 0.0,
            "attack_id": "demo-attack-" + str(self.event_seq),
        }

    async def handle(self, websocket):
        player_id = None
        try:
            try:
                raw = await asyncio.wait_for(websocket.recv(), HELLO_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                await websocket.close(code=1008, reason="ClientHello required")
                return
            hello = decode_hello(raw)
            if hello is None or not self.claim(*hello, websocket):
                await websocket.close(code=1008, reason="Invalid or occupied player slot")
                return
            _, player_id = hello
            await websocket.send(encode(self.welcome(player_id)))
            await websocket.send(encode(self.state()))
            self.ready[player_id] = websocket
            async for _ in websocket:
                # Phase 2 stops at the handshake. Gameplay requests need the
                # Ultra96 Game Engine handler, not an invented echo response.
                await websocket.close(code=1008, reason="Unsupported client message")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if player_id is not None:
                self.release(player_id, websocket)

    async def broadcast(self, message):
        sockets = tuple(self.ready.values())
        if not sockets:
            return 0
        payload = encode(message)
        await asyncio.gather(
            *(socket.send(payload) for socket in sockets), return_exceptions=True
        )
        return len(sockets)

    async def broadcast_state(self):
        return await self.broadcast(self.state())

    async def broadcast_demo_punch(self, source_player, punch, confidence, intensity):
        return await self.broadcast(
            self.demo_punch(source_player, punch, confidence, intensity)
        )


async def periodic_states(hub, interval_seconds=1.0):
    while True:
        await asyncio.sleep(interval_seconds)
        await hub.broadcast_state()
