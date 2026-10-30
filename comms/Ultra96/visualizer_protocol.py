"""Protocol-v2 WSS handshake, attack ledger, and transport for the Game Engine."""

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass

import websockets
from game_engine import GameEngine


PROTOCOL_VERSION = 2
MAX_MESSAGE_BYTES = 65536
HELLO_TIMEOUT_SECONDS = 5
MAX_ATTACK_RECORDS = 10000
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
PUNCHES = frozenset((
    "JAB", "CROSS", "LEFT_HOOK", "RIGHT_HOOK",
    "LEFT_UPPERCUT", "RIGHT_UPPERCUT",
))
OBSERVATIONS = frozenset((
    "TARGET_TRACKED", "TARGET_NOT_TRACKED", "TRACKING_UNAVAILABLE",
))
def decode_observation(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    required = {"type", "protocol_version", "match_id", "stream_id", "attack_id",
                "observer_player", "observation", "client_timestamp"}
    if not required <= set(value) or set(value) - (required | {"target_age_ms"}):
        return None
    if (value["type"] != "PunchObservation" or
            type(value["protocol_version"]) is not int or
            value["protocol_version"] != PROTOCOL_VERSION or
            any(not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key])
                for key in ("match_id", "stream_id", "attack_id")) or
            type(value["observer_player"]) is not int or
            value["observer_player"] not in (1, 2) or
            not isinstance(value["observation"], str) or
            value["observation"] not in OBSERVATIONS or
            type(value["client_timestamp"]) is not int or
            value["client_timestamp"] < 0):
        return None
    age = value.get("target_age_ms")
    if (value["observation"] == "TARGET_TRACKED" and age is None or
            age is not None and (type(age) is not int or age < 0 or age > 1000)):
        return None
    return value


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


@dataclass
class AttackRecord:
    """One attack's immutable request and its PENDING -> RESOLVED transition."""

    attack_id: str
    source_player: int
    punch: str
    confidence: float
    intensity: float
    deadline: float
    attempt: dict
    observation_future: asyncio.Future
    result_future: asyncio.Future
    bound_socket: object = None
    observation: str = None
    final_event: dict = None
    last_replay_session: int = None
    first_delivery: bool = False

    @property
    def status(self):
        return "RESOLVED" if self.final_event is not None else "PENDING"


class PhoneHub:
    """Two-player WSS transport; GameEngine alone owns gameplay state."""

    def __init__(self, match_id="match-demo-001", engine=None, required_players=2):
        if required_players not in (1, 2):
            raise ValueError("required_players must be 1 or 2")
        self.match_id = match_id
        self.stream_id = "ultra96-" + uuid.uuid4().hex[:16]
        self.engine = engine or GameEngine()
        self.required_players = required_players
        self.owners = {}             # player_id -> stable client_id
        self.active = {}             # player_id -> socket, including joining
        self.ready = {}              # player_id -> socket, after welcome/state
        self.event_seq = 0
        self.state_seq = 0
        self.attacks = {}           # full-match ledger, including resolved IDs
        self.rejected_attacks = {}  # rejected IDs cannot become valid on retry
        self.guard_actions = {}     # stable classified guard ID -> accepted/rejected result
        self.pending = {}           # unresolved subset for reconnect delivery
        self.resolver_tasks = set()
        self.session_serial = 0
        self.broadcast_lock = asyncio.Lock()

    @property
    def health(self):
        """Read-only compatibility view; mutations belong to GameEngine."""
        return {slot: player.health for slot, player in self.engine.players.items()}

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

    async def release(self, player_id, websocket):
        if self.active.get(player_id) is websocket:
            del self.active[player_id]
        was_ready = self.ready.get(player_id) is websocket
        if self.ready.get(player_id) is websocket:
            del self.ready[player_id]
        for record in self.pending.values():
            if record.source_player == player_id and record.bound_socket is websocket:
                record.bound_socket = None
        if was_ready and len(self.ready) < self.required_players:
            async with self.broadcast_lock:
                if self.engine.pause():
                    await self.broadcast(self.state())

    def welcome(self, player_id):
        return {
            "type": "ServerWelcome", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "player_id": player_id, "server_timestamp": int(time.time() * 1000),
            "heartbeat_interval_ms": 5000,
        }

    def state(self):
        self.state_seq += 1
        return {
            "type": "MatchState", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "seq": self.state_seq, "timestamp": int(time.time() * 1000),
            **self.engine.snapshot(),
        }

    async def request_punch(self, source_player, punch, confidence, intensity,
                            response_timeout_ms=750, attack_id=None):
        """Resolve one stable ID once; duplicate engine calls share its result."""
        if (source_player not in (1, 2) or punch not in PUNCHES or
                not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                        for v in (confidence, intensity)) or
                type(response_timeout_ms) is not int or
                not 100 <= response_timeout_ms <= 2000 or
                (attack_id is not None and
                 (not isinstance(attack_id, str) or not IDENTIFIER.fullmatch(attack_id)))):
            raise ValueError("invalid punch request")
        if attack_id is None:
            attack_id = "attack-" + uuid.uuid4().hex
        parameters = (source_player, punch, confidence, intensity, response_timeout_ms)
        async with self.broadcast_lock:
            rejected = self.rejected_attacks.get(attack_id)
            if rejected is not None:
                if rejected != parameters:
                    raise ValueError("conflicting duplicate attack ID")
                return None
            existing = self.attacks.get(attack_id)
            if existing is not None:
                if (existing.source_player != source_player or existing.punch != punch or
                        existing.confidence != confidence or existing.intensity != intensity or
                        existing.attempt["response_timeout_ms"] != response_timeout_ms):
                    raise ValueError("conflicting duplicate attack ID")
                result_future = existing.result_future
            else:
                if len(self.attacks) + len(self.rejected_attacks) >= MAX_ATTACK_RECORDS:
                    raise RuntimeError("attack ledger full; start a new match")
                if not self.engine.try_attack(source_player, punch):
                    self.rejected_attacks[attack_id] = parameters
                    await self._broadcast_transitions_locked()
                    await self.broadcast(self.state())
                    return None

                target_player = 3 - source_player
                loop = asyncio.get_running_loop()
                attempt = {
                    "type": "PunchAttempt", "protocol_version": PROTOCOL_VERSION,
                    "match_id": self.match_id, "stream_id": self.stream_id,
                    "attack_id": attack_id, "timestamp": int(time.time() * 1000),
                    "source_player": source_player, "target_player": target_player,
                    "punch": punch, "confidence": confidence, "intensity": intensity,
                    "response_timeout_ms": response_timeout_ms,
                }
                record = AttackRecord(
                    attack_id, source_player, punch, confidence, intensity,
                    time.monotonic() + response_timeout_ms / 1000, attempt,
                    loop.create_future(), loop.create_future(),
                )
                self.attacks[attack_id] = record
                self.pending[attack_id] = record
                resolver = asyncio.create_task(self._resolve_attack(record))
                self.resolver_tasks.add(resolver)
                resolver.add_done_callback(self.resolver_tasks.discard)
                result_future = record.result_future
        return await asyncio.shield(result_future)

    async def request_guard(self, source_player, active=True, confidence=1.0,
                            guard_id=None):
        """Accept a classified server-side guard start/end once per stable ID."""
        if (source_player not in (1, 2) or type(active) is not bool or
                type(confidence) not in (int, float) or
                not math.isfinite(confidence) or not 0 <= confidence <= 1 or
                (guard_id is not None and
                 (not isinstance(guard_id, str) or not IDENTIFIER.fullmatch(guard_id)))):
            raise ValueError("invalid guard request")
        if guard_id is None:
            guard_id = "guard-" + uuid.uuid4().hex
        async with self.broadcast_lock:
            existing = self.guard_actions.get(guard_id)
            if existing is not None:
                if existing[:3] != (source_player, active, confidence):
                    raise ValueError("conflicting duplicate guard ID")
                return existing[3]
            if len(self.guard_actions) >= MAX_ATTACK_RECORDS:
                raise RuntimeError("guard ledger full; start a new match")
            accepted = (self.engine.start_guard(source_player) if active else
                        self.engine.end_guard(source_player))
            if not accepted:
                self.guard_actions[guard_id] = (source_player, active, confidence, None)
                await self._broadcast_transitions_locked()
                await self.broadcast(self.state())
                return None
            self.event_seq += 1
            event = {
                "type": "GameEvent", "protocol_version": PROTOCOL_VERSION,
                "match_id": self.match_id, "stream_id": self.stream_id,
                "seq": self.event_seq, "timestamp": int(time.time() * 1000),
                "event": "GUARD", "source_player": source_player,
                "target_player": 3 - source_player, "punch": "",
                "confidence": confidence, "intensity": 0.0,
                "outcome": "NONE", "damage": 0.0,
                "attack_id": guard_id,
            }
            self.guard_actions[guard_id] = (source_player, active, confidence, event)
            await self.broadcast(event)
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
        return event

    async def _send_attempt(self, record, socket):
        async with self.broadcast_lock:
            if not record.first_delivery:
                # Give the phone the advertised window even when the resolver
                # task starts a few milliseconds after request_punch().
                record.deadline = time.monotonic() + record.attempt["response_timeout_ms"] / 1000
                record.first_delivery = True
            remaining_ms = math.ceil((record.deadline - time.monotonic()) * 1000)
            if record.final_event is not None or remaining_ms < 100:
                return
            record.bound_socket = socket
            attempt = dict(record.attempt)
            attempt["response_timeout_ms"] = min(2000, remaining_ms)
            try:
                await socket.send(encode(attempt))
            except (websockets.exceptions.ConnectionClosed, OSError):
                if record.bound_socket is socket:
                    record.bound_socket = None

    async def _resolve_attack(self, record):
        socket = self.ready.get(record.source_player)
        if socket is not None:
            await self._send_attempt(record, socket)
        try:
            observation = await asyncio.wait_for(
                asyncio.shield(record.observation_future),
                max(0, record.deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            observation = "TRACKING_UNAVAILABLE"

        async with self.broadcast_lock:
            # The event-loop mutation below has no await until the final record
            # is stored, so timeout/retry/reconnect paths cannot apply twice.
            if record.final_event is not None:
                return
            self.pending.pop(record.attack_id, None)
            target_player = 3 - record.source_player
            outcome, damage = self.engine.resolve_punch(
                record.source_player, record.punch, record.intensity,
                observation == "TARGET_TRACKED")
            self.event_seq += 1
            event = {
                "type": "GameEvent", "protocol_version": PROTOCOL_VERSION,
                "match_id": self.match_id, "stream_id": self.stream_id,
                "seq": self.event_seq, "timestamp": int(time.time() * 1000),
                "event": "PUNCH", "source_player": record.source_player,
                "target_player": target_player, "punch": record.punch,
                "confidence": record.confidence, "intensity": record.intensity,
                "outcome": outcome, "damage": damage,
                "attack_id": record.attack_id,
            }
            record.final_event = event
            record.bound_socket = None
            await self.broadcast(event)
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
            record.result_future.set_result(event)

    async def _broadcast_transitions_locked(self):
        for phase in self.engine.pop_transitions():
            self.event_seq += 1
            await self.broadcast({
                "type": "GameEvent", "protocol_version": PROTOCOL_VERSION,
                "match_id": self.match_id, "stream_id": self.stream_id,
                "seq": self.event_seq, "timestamp": int(time.time() * 1000),
                "event": "ROUND_TRANSITION", "source_player": 1,
                "target_player": 2, "punch": "", "confidence": 1.0,
                "intensity": 0.0, "outcome": "NONE", "damage": 0.0,
            })

    async def _replay_result(self, record, websocket, session_id):
        if record.last_replay_session == session_id:
            return
        record.last_replay_session = session_id
        async with self.broadcast_lock:
            try:
                await websocket.send(encode(record.final_event))
                await websocket.send(encode(self.state()))
            except (websockets.exceptions.ConnectionClosed, OSError):
                pass

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
            client_id, player_id = hello
            self.session_serial += 1
            session_id = self.session_serial
            async with self.broadcast_lock:
                await websocket.send(encode(self.welcome(player_id)))
                self.ready[player_id] = websocket
                resumed = False
                if len(self.ready) >= self.required_players:
                    resumed = self.engine.start() or self.engine.resume()
                snapshot = self.state()
                await websocket.send(encode(snapshot))
                if resumed:
                    payload = encode(snapshot)
                    await asyncio.gather(
                        *(socket.send(payload) for slot, socket in self.ready.items()
                          if slot != player_id), return_exceptions=True)
            for record in tuple(self.pending.values()):
                if record.source_player == player_id and not record.observation_future.done():
                    await self._send_attempt(record, websocket)
            async for raw in websocket:
                observation = decode_observation(raw)
                if observation is None:
                    await websocket.close(code=1008, reason="Invalid PunchObservation")
                    break
                record = self.attacks.get(observation["attack_id"])
                if (record is None or record.source_player != player_id or
                        self.owners.get(player_id) != client_id or
                        observation["observer_player"] != player_id or
                        observation["match_id"] != self.match_id or
                        observation["stream_id"] != self.stream_id):
                    continue
                if record.final_event is not None:
                    if record.observation in (None, observation["observation"]):
                        await self._replay_result(record, websocket, session_id)
                    continue
                if (record.bound_socket is not websocket or
                        time.monotonic() >= record.deadline or
                        record.observation_future.done()):
                    continue
                record.observation = observation["observation"]
                record.observation_future.set_result(record.observation)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if player_id is not None:
                await self.release(player_id, websocket)

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
        async with self.broadcast_lock:
            self.engine.advance()
            await self._broadcast_transitions_locked()
            return await self.broadcast(self.state())

async def periodic_states(hub, interval_seconds=1.0):
    while True:
        await asyncio.sleep(interval_seconds)
        await hub.broadcast_state()
