"""Protocol-v2 WSS handshake, attack ledger, and transport for the Game Engine."""

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass

import websockets
from websockets.exceptions import ConnectionClosed
from game_engine import GameEngine
from contract_validation import decode, validator


PROTOCOL_VERSION = 2
MAX_MESSAGE_BYTES = 65536
HELLO_TIMEOUT_SECONDS = 5
MAX_ATTACK_RECORDS = 10000
SEND_TIMEOUT_SECONDS = 1.0
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
        value = decode(raw)
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
        message = decode(raw)
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
    phase_epoch: int = 0
    cancelled: bool = False
    observation_payload: dict = None

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
        self.engine = engine or GameEngine(required_players=required_players)
        self.engine.required_players = required_players
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
        self.commands = set()
        self.pickup_actions = {}
        self.pickups = {}
        self.pending_pickups = {}
        self.command_validator = validator("player-command")
        self.pickup_validator = validator("pickup-observation")

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
        if was_ready:
            async with self.broadcast_lock:
                self.engine.set_connected(player_id, False)
                await self._cancel_pickups_locked("OBSERVATION_TIMEOUT", player_id)
                await self._broadcast_transitions_locked()
                await self.broadcast(self.state())

    def welcome(self, player_id):
        return {
            "type": "ServerWelcome", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "player_id": player_id, "server_timestamp": int(time.time() * 1000),
            "heartbeat_interval_ms": 5000,
            "supports_player_commands": True,
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
                record.phase_epoch = self.engine.fight_epoch
                self.attacks[attack_id] = record
                self.pending[attack_id] = record
                resolver = asyncio.create_task(self._resolve_attack(record))
                self.resolver_tasks.add(resolver)
                resolver.add_done_callback(self.resolver_tasks.discard)
                result_future = record.result_future
                await self.broadcast(self.state())
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
            if record.final_event is not None or record.cancelled or remaining_ms < 100:
                return
            record.bound_socket = socket
            attempt = dict(record.attempt)
            attempt["response_timeout_ms"] = min(2000, remaining_ms)
            try:
                await self.send(socket, attempt)
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
                observation == "TARGET_TRACKED" and not record.cancelled and
                record.phase_epoch == self.engine.fight_epoch)
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
        self._interrupt_attacks()
        if self.engine.phase != "FIGHTING":
            await self._cancel_pickups_locked("MATCH_NOT_ACTIVE")
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
                await self.send(websocket, record.final_event)
                await self.send(websocket, self.state())
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
                if not await self.send(websocket, self.welcome(player_id)):
                    return
                self.ready[player_id] = websocket
                self.engine.set_connected(player_id, True)
                snapshot = self.state()
                await self.send(websocket, snapshot)
                await asyncio.gather(*(self.send(socket, snapshot)
                    for slot, socket in self.ready.items() if slot != player_id))
            for record in tuple(self.pending.values()):
                if record.source_player == player_id and not record.observation_future.done():
                    await self._send_attempt(record, websocket)
            async for raw in websocket:
                message = decode(raw)
                if message is not None and message.get("type") == "PlayerCommand":
                    await self.player_command(player_id, message)
                    continue
                if message is not None and message.get("type") == "PickupObservation":
                    if not self.pickup_validator.is_valid(message):
                        await websocket.close(code=1008, reason="Invalid PickupObservation")
                        break
                    await self.pickup_observation(player_id, message, websocket)
                    continue
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
                    if record.observation_payload is None or record.observation_payload == observation:
                        await self._replay_result(record, websocket, session_id)
                    continue
                if (record.bound_socket is not websocket or
                        time.monotonic() >= record.deadline or
                        record.observation_future.done()):
                    continue
                record.observation = observation["observation"]
                record.observation_payload = dict(observation)
                record.observation_future.set_result(record.observation)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if player_id is not None:
                await self.release(player_id, websocket)

    def _interrupt_attacks(self):
        for record in self.pending.values():
            if self.engine.phase != "FIGHTING" or record.phase_epoch != self.engine.fight_epoch:
                record.cancelled = True
                if not record.observation_future.done():
                    record.observation_future.set_result("TRACKING_UNAVAILABLE")

    async def send(self, websocket, message):
        """No peer may indefinitely block the match's serialized mutation loop."""
        try:
            await asyncio.wait_for(websocket.send(encode(message)), SEND_TIMEOUT_SECONDS)
            return True
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed, OSError):
            async def disconnect():
                try:
                    await asyncio.wait_for(websocket.close(code=1011, reason="Send deadline"), 1)
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed, OSError):
                    if getattr(websocket, "transport", None):
                        websocket.transport.abort()
                for player, socket in tuple(self.active.items()):
                    if socket is websocket:
                        await self.release(player, websocket)
            task = asyncio.create_task(disconnect())
            self.resolver_tasks.add(task)
            task.add_done_callback(self.resolver_tasks.discard)
            return False

    def _identity_matches(self, message, player):
        return (message.get("match_id") == self.match_id and
                message.get("stream_id") == self.stream_id and
                message.get("player_id") == player)

    async def player_command(self, player, message):
        # Unknown commands and commands from another phase are harmless no-ops.
        if not self.command_validator.is_valid(message) or not self._identity_matches(message, player):
            return False
        key = (player, message["command_id"])
        async with self.broadcast_lock:
            if key in self.commands or len(self.commands) >= MAX_ATTACK_RECORDS:
                return False
            self.commands.add(key)
            accepted = self.engine.command(player, message["command"])
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
            return accepted

    async def operator_pause(self):
        async with self.broadcast_lock:
            paused = self.engine.pause()
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
            return paused

    async def spawn_health(self, player):
        """Explicit operator diagnostic; normal gameplay uses the fighting-time schedule."""
        async with self.broadcast_lock:
            self.engine.advance()
            spawned = self.engine.spawn_health(player)
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
            return spawned

    async def request_pickup(self, player, action_id):
        if (type(player) is not int or player not in (1, 2) or
                not isinstance(action_id, str) or not IDENTIFIER.fullmatch(action_id)):
            raise ValueError("invalid classified pickup action")
        key = (player, action_id)
        async with self.broadcast_lock:
            if key in self.pickup_actions:
                request_id = self.pickup_actions[key]
                prior = self.pickups.get(request_id)
                if prior and prior["result"] and player in self.ready:
                    await self.send(self.ready[player], prior["result"])
                    await self.send(self.ready[player], self.state())
                return prior["check"] if prior else None
            if len(self.pickup_actions) >= MAX_ATTACK_RECORDS:
                return None
            self.pickup_actions[key] = None  # rejected IDs can never become new actions later
            self.engine.advance()
            await self._broadcast_transitions_locked()
            item = self.engine.items.get(player)
            if (self.engine.phase != "FIGHTING" or not item or player not in self.ready or
                    player in self.pending_pickups):
                return None
            request_id = "pickup-" + uuid.uuid4().hex
            check = dict(type="PickupCheck", protocol_version=2, match_id=self.match_id,
                stream_id=self.stream_id, request_id=request_id, item_id=item[0]["id"],
                player_id=player, response_timeout_ms=750)
            self.pickup_actions[key] = request_id
            self.pickups[request_id] = dict(check=check, deadline=time.monotonic()+.75,
                expiry=item[1], result=None, observation=None)
            self.pending_pickups[player] = request_id
            await self.send(self.ready[player], check)
            return check

    async def _pickup_result_locked(self, record, reason):
        if record["result"] is not None:
            return
        check = record["check"]
        result = dict(type="PickupResult", protocol_version=2, match_id=self.match_id,
            stream_id=self.stream_id, request_id=check["request_id"], item_id=check["item_id"],
            player_id=check["player_id"], accepted=reason == "ACCEPTED", reason=reason,
            server_timestamp=int(time.time()*1000))
        record["result"] = result
        self.pending_pickups.pop(check["player_id"], None)
        if check["player_id"] in self.ready:
            await self.send(self.ready[check["player_id"]], result)

    async def _cancel_pickups_locked(self, reason, player=None):
        for owner, request_id in tuple(self.pending_pickups.items()):
            if player is None or player == owner:
                await self._pickup_result_locked(self.pickups[request_id], reason)

    async def _expire_pickups_locked(self):
        for request_id in tuple(self.pending_pickups.values()):
            record = self.pickups[request_id]
            if time.monotonic() >= record["deadline"]:
                await self._pickup_result_locked(record, "OBSERVATION_TIMEOUT")
            elif self.engine.fight_time >= record["expiry"]:
                await self._pickup_result_locked(record, "EXPIRED")

    async def pickup_observation(self, player, message, websocket):
        if not self.pickup_validator.is_valid(message) or not self._identity_matches(message, player):
            return
        async with self.broadcast_lock:
            record = self.pickups.get(message["request_id"])
            if (record is None or self.ready.get(player) is not websocket or
                    any(message[field] != record["check"][field] for field in
                        ("player_id", "item_id", "match_id", "stream_id"))):
                return
            if record["result"]:
                if record["observation"] is None or record["observation"] == message:
                    await self.send(websocket, record["result"])
                    await self.send(websocket, self.state())
                return
            self.engine.advance()
            await self._broadcast_transitions_locked()
            await self._expire_pickups_locked()
            if record["result"]:
                return
            record["observation"] = dict(message)
            reason, gain = message["observation"], 0.0
            if reason == "AVAILABLE":
                reason, gain = self.engine.collect_health(player, message["item_id"],
                                                          message["observed_distance_m"])
            await self._pickup_result_locked(record, reason)
            if reason == "ACCEPTED":
                self.event_seq += 1
                await self.broadcast(dict(type="GameEvent", protocol_version=2,
                    match_id=self.match_id, stream_id=self.stream_id, seq=self.event_seq,
                    timestamp=int(time.time()*1000), event="ITEM_PICKUP", source_player=player,
                    target_player=player, punch="", confidence=1.0, intensity=0.0, outcome="NONE",
                    damage=0.0, request_id=message["request_id"], item_id=message["item_id"],
                    item_type="HEALTH", hand=message["hand"], magnitude=gain, effect_duration_ms=0))
            await self.broadcast(self.state())

    async def close(self):
        for task in tuple(self.resolver_tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.resolver_tasks), return_exceptions=True)

    async def broadcast(self, message):
        sockets = tuple(self.ready.values())
        if not sockets:
            return 0
        await asyncio.gather(*(self.send(socket, message) for socket in sockets))
        return len(sockets)

    async def broadcast_state(self):
        async with self.broadcast_lock:
            self.engine.advance()
            await self._expire_pickups_locked()
            await self._broadcast_transitions_locked()
            return await self.broadcast(self.state())

async def periodic_states(hub, interval_seconds=0.1):
    while True:
        await asyncio.sleep(interval_seconds)
        await hub.broadcast_state()
