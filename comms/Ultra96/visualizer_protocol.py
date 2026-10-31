"""Protocol-v2 WSS handshake, attack ledger, and transport for the Game Engine."""

import asyncio
import json
import math
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass

import websockets
from game_engine import COMMANDS, GameEngine


PROTOCOL_VERSION = 2
MAX_MESSAGE_BYTES = 65536
HELLO_TIMEOUT_SECONDS = 5
SEND_TIMEOUT_SECONDS = 1.0     # a phone that can't take a message in 1 s is dropped
STATE_INTERVAL_SECONDS = 0.1   # MatchState period promised by docs/protocol.md
PING_INTERVAL_SECONDS = 5      # websockets keepalive: a dead phone is noticed in ~10 s
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


COMMAND_KEYS = frozenset(("type", "protocol_version", "match_id", "stream_id",
                          "player_id", "command_id", "command", "timestamp"))
RECENT_COMMAND_IDS = 256
PICKUP_TIMEOUT_MS = 750
PICKUP_KEYS = frozenset(("type", "protocol_version", "match_id", "stream_id", "request_id",
                         "item_id", "player_id", "observation", "client_timestamp"))
PICKUP_OBSERVATIONS = frozenset(("AVAILABLE", "ITEM_UNAVAILABLE", "TRACKING_UNAVAILABLE"))


def decode_pickup_observation(raw):
    """Return a canonical PickupObservation dict, or None.

    AVAILABLE must carry a finite, non-negative observed_distance_m and a hand;
    the other observations must carry neither (never a made-up zero distance).
    """
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not PICKUP_KEYS <= set(value):
        return None
    available = value.get("observation") == "AVAILABLE"
    extra = set(value) - PICKUP_KEYS
    if extra != ({"observed_distance_m", "hand"} if available else set()):
        return None
    if (value["type"] != "PickupObservation" or
            type(value["protocol_version"]) is not int or
            value["protocol_version"] != PROTOCOL_VERSION or
            any(not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key])
                for key in ("match_id", "stream_id", "request_id", "item_id")) or
            type(value["player_id"]) is not int or value["player_id"] not in (1, 2) or
            value["observation"] not in PICKUP_OBSERVATIONS or
            type(value["client_timestamp"]) is not int or value["client_timestamp"] < 0):
        return None
    if available:
        distance = value["observed_distance_m"]
        if (type(distance) not in (int, float) or not math.isfinite(distance) or
                distance < 0 or value["hand"] not in ("LEFT", "RIGHT")):
            return None
    return value


def message_type(raw):
    """The "type" of a JSON object message, or None if it isn't one."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    kind = value.get("type") if isinstance(value, dict) else None
    return kind if isinstance(kind, str) else None


def decode_command(raw):
    """Return a canonical PlayerCommand dict, or None (exact keys, like ClientHello)."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != COMMAND_KEYS:
        return None
    if (value["type"] != "PlayerCommand" or
            type(value["protocol_version"]) is not int or
            value["protocol_version"] != PROTOCOL_VERSION or
            any(not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key])
                for key in ("match_id", "stream_id", "command_id")) or
            type(value["player_id"]) is not int or value["player_id"] not in (1, 2) or
            not isinstance(value["command"], str) or value["command"] not in COMMANDS or
            type(value["timestamp"]) is not int or value["timestamp"] < 0):
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


async def send_bounded(socket, payload):
    """Send one frame, or drop that phone if it stalls; never block the others.

    Returns False when the phone is gone. Its handler sees the close and
    releases the slot (which pauses a running fight).
    """
    try:
        await asyncio.wait_for(socket.send(payload), SEND_TIMEOUT_SECONDS)
        return True
    except asyncio.TimeoutError:
        transport = getattr(socket, "transport", None)
        if transport is not None:
            transport.abort()
        return False
    except (websockets.exceptions.ConnectionClosed, OSError):
        return False


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
    fight_epoch: int = 0          # a pause in between means it can't land
    bound_socket: object = None
    observation: str = None
    final_event: dict = None
    last_replay_session: int = None
    first_delivery: bool = False

    @property
    def status(self):
        return "RESOLVED" if self.final_event is not None else "PENDING"


@dataclass
class PickupRequest:
    """One pickup action: its private PickupCheck, then exactly one result."""

    check: dict
    deadline: float
    result: dict = None
    observation: dict = None


class PhoneHub:
    """Two-player WSS transport; GameEngine alone owns gameplay state."""

    def __init__(self, match_id="match-demo-001", engine=None, required_players=2,
                 auto_start=False):
        """auto_start=True keeps the old behaviour (joining starts or resumes the
        fight) for phone-less AI runs; normally the phones' PlayerCommands drive
        LOBBY -> CALIBRATING -> COUNTDOWN -> FIGHTING."""
        if required_players not in (1, 2):
            raise ValueError("required_players must be 1 or 2")
        self.match_id = match_id
        self.stream_id = "ultra96-" + uuid.uuid4().hex[:16]
        self.engine = engine or GameEngine()
        self.engine.required_players = required_players
        self.required_players = required_players
        self.auto_start = auto_start
        self.command_ids = {1: deque(maxlen=RECENT_COMMAND_IDS),
                            2: deque(maxlen=RECENT_COMMAND_IDS)}
        self.pickups = {}           # request_id -> PickupRequest, for the whole match
        self.pending_pickups = {}   # player -> request_id; one check at a time
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
        # A slot is taken only while a phone holds it. A different client_id may
        # take a free slot (e.g. after an app reinstall); client_id was never auth.
        if player_id in self.active:
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
                # A pending pickup check can't be answered now: time it out
                # without consuming the item.
                request_id = self.pending_pickups.get(player_id)
                if request_id is not None:
                    self._resolve_pickup_locked(self.pickups[request_id], "OBSERVATION_TIMEOUT")
                # Mid-fight (or countdown) this pauses; ready flags drop either way.
                # At MATCH_END the last one out (or the last holdout) resets the match.
                match = self.engine.match_number
                self.engine.set_connected(player_id, False)
                await self._after_reset_locked(match)
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

    async def player_command(self, player_id, client_id, raw):
        """Apply one PlayerCommand from a bound phone. Invalid, foreign or
        repeated commands are ignored (never a socket close), per protocol.md."""
        command = decode_command(raw)
        if (command is None or command["player_id"] != player_id or
                self.owners.get(player_id) != client_id or
                command["match_id"] != self.match_id or
                command["stream_id"] != self.stream_id):
            print(f"[COMMAND] ignored invalid or foreign command from P{player_id}", flush=True)
            return False
        recent = self.command_ids[player_id]
        if command["command_id"] in recent:
            return False   # a retry of something already applied
        recent.append(command["command_id"])
        async with self.broadcast_lock:
            match = self.engine.match_number
            changed = self.engine.command(player_id, command["command"])
            print(f"[COMMAND] P{player_id} {command['command']} -> "
                  f"{self.engine.phase}{'' if changed else ' (no change)'}", flush=True)
            await self._after_reset_locked(match)
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
        return changed

    async def operator_reset(self):
        """Server-side new match (keyboard 'n'): back to LOBBY from any phase."""
        async with self.broadcast_lock:
            match = self.engine.match_number
            self.engine.reset_match()
            await self._after_reset_locked(match)
            await self.broadcast(self.state())

    async def _after_reset_locked(self, match_before):
        """Tidy up after the engine started a new match (no-op otherwise).

        A pending pickup check can't count any more, so it resolves as
        MATCH_NOT_ACTIVE. Resolved attack/guard/pickup entries are dropped so
        the ledgers stay bounded over many matches; still-pending attacks stay
        and resolve as MISS (the fight epoch moved on). match_id, stream_id and
        the seq counters are unchanged: phones just see a fresh LOBBY state.
        """
        if self.engine.match_number == match_before:
            return
        for player_id, request_id in tuple(self.pending_pickups.items()):
            result = self._resolve_pickup_locked(self.pickups[request_id], "MATCH_NOT_ACTIVE")
            socket = self.ready.get(player_id)
            if socket is not None:
                await send_bounded(socket, encode(result))
        self.pickups.clear()
        self.attacks = {key: record for key, record in self.attacks.items()
                        if record.final_event is None}
        self.rejected_attacks.clear()
        self.guard_actions.clear()
        if self.auto_start and len(self.ready) >= self.required_players:
            self.engine.start()
        print(f"[MATCH] match {self.engine.match_number} starts in {self.engine.phase}", flush=True)

    async def operator_pause(self):
        """Server-side pause (keyboard 'p'); the referee's stop."""
        async with self.broadcast_lock:
            paused = self.engine.pause()
            await self._broadcast_transitions_locked()
            await self.broadcast(self.state())
        return paused

    # ----- Health pickups (docs/protocol.md "Player-specific item pickups") -----

    async def spawn_health(self, player_id):
        """Explicit spawn trigger; MatchState.active_items carries the item."""
        async with self.broadcast_lock:
            item = self.engine.spawn_health(player_id)
            if item is not None:
                await self.broadcast(self.state())
        return item

    async def request_pickup(self, player_id, action_id):
        """A pickup action (wearable or keyboard) with a stable action ID.

        Sends a private PickupCheck to that player's phone. Retrying the same
        action ID never creates a second effect: it replays the cached result.
        Returns the PickupCheck sent, the cached result, or None if ignored.
        """
        if (player_id not in (1, 2) or not isinstance(action_id, str) or
                not IDENTIFIER.fullmatch(action_id)):
            raise ValueError("invalid pickup action")
        request_id = f"p{player_id}:{action_id}"
        if len(request_id) > 64:
            raise ValueError("pickup action ID too long")
        async with self.broadcast_lock:
            prior = self.pickups.get(request_id)
            if prior is not None:
                if prior.result is not None and player_id in self.ready:
                    socket = self.ready[player_id]
                    await send_bounded(socket, encode(prior.result))
                    await send_bounded(socket, encode(self.state()))
                return prior.result
            socket = self.ready.get(player_id)
            item = self.engine.pickup_target(player_id)
            if (socket is None or item is None or player_id in self.pending_pickups or
                    len(self.pickups) >= MAX_ATTACK_RECORDS):
                return None
            check = {
                "type": "PickupCheck", "protocol_version": PROTOCOL_VERSION,
                "match_id": self.match_id, "stream_id": self.stream_id,
                "request_id": request_id, "item_id": item.item_id,
                "player_id": player_id, "response_timeout_ms": PICKUP_TIMEOUT_MS,
            }
            self.pickups[request_id] = PickupRequest(
                check, time.monotonic() + PICKUP_TIMEOUT_MS / 1000)
            self.pending_pickups[player_id] = request_id
            await send_bounded(socket, encode(check))
            timer = asyncio.create_task(self._pickup_timeout(request_id))
            self.resolver_tasks.add(timer)
            timer.add_done_callback(self.resolver_tasks.discard)
        return check

    def _resolve_pickup_locked(self, request, reason):
        check = request.check
        request.result = {
            "type": "PickupResult", "protocol_version": PROTOCOL_VERSION,
            "match_id": self.match_id, "stream_id": self.stream_id,
            "request_id": check["request_id"], "item_id": check["item_id"],
            "player_id": check["player_id"], "accepted": reason == "ACCEPTED",
            "reason": reason, "server_timestamp": int(time.time() * 1000),
        }
        if self.pending_pickups.get(check["player_id"]) == check["request_id"]:
            del self.pending_pickups[check["player_id"]]
        return request.result

    async def _pickup_timeout(self, request_id):
        request = self.pickups[request_id]
        await asyncio.sleep(max(0.0, request.deadline - time.monotonic()))
        async with self.broadcast_lock:
            if request.result is not None:
                return
            result = self._resolve_pickup_locked(request, "OBSERVATION_TIMEOUT")
            socket = self.ready.get(result["player_id"])
            if socket is not None:
                await send_bounded(socket, encode(result))

    async def pickup_observation(self, player_id, client_id, raw):
        """Judge the phone's reach evidence; invalid or foreign input is ignored."""
        observation = decode_pickup_observation(raw)
        request = (self.pickups.get(observation["request_id"])
                   if observation is not None else None)
        if (request is None or observation["player_id"] != player_id or
                self.owners.get(player_id) != client_id or
                any(observation[key] != request.check[key]
                    for key in ("match_id", "stream_id", "item_id", "player_id"))):
            print(f"[PICKUP] ignored invalid or foreign observation from P{player_id}", flush=True)
            return None
        async with self.broadcast_lock:
            socket = self.ready.get(player_id)
            if request.result is not None:
                # A retry of the same evidence replays; different evidence is ignored.
                if request.observation in (None, observation) and socket is not None:
                    await send_bounded(socket, encode(request.result))
                    await send_bounded(socket, encode(self.state()))
                return request.result
            if time.monotonic() >= request.deadline:
                reason, gained = "OBSERVATION_TIMEOUT", 0.0
            else:
                reason, gained = self.engine.collect_health(
                    player_id, observation["item_id"], observation["observation"],
                    observation.get("observed_distance_m", 0.0))
            request.observation = observation
            result = self._resolve_pickup_locked(request, reason)
            print(f"[PICKUP] P{player_id} {reason}"
                  + (f" +{gained:g} HP" if reason == "ACCEPTED" else ""), flush=True)
            if socket is not None:
                await send_bounded(socket, encode(result))
            if reason == "ACCEPTED":
                self.event_seq += 1
                await self.broadcast({
                    "type": "GameEvent", "protocol_version": PROTOCOL_VERSION,
                    "match_id": self.match_id, "stream_id": self.stream_id,
                    "seq": self.event_seq, "timestamp": int(time.time() * 1000),
                    "event": "ITEM_PICKUP", "source_player": player_id,
                    "target_player": player_id, "punch": "", "confidence": 1.0,
                    "intensity": 0.0, "outcome": "NONE", "damage": 0.0,
                    "request_id": observation["request_id"],
                    "item_id": observation["item_id"], "item_type": "HEALTH",
                    "hand": observation["hand"], "magnitude": gained,
                    "effect_duration_ms": 0,
                })
                await self.broadcast(self.state())
            return result

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
                    fight_epoch=self.engine.fight_epoch,
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
            if not await send_bounded(socket, encode(attempt)):
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
            # A punch thrown before a pause can't land after it: MISS, once.
            landed = (observation == "TARGET_TRACKED" and
                      record.fight_epoch == self.engine.fight_epoch)
            outcome, damage = self.engine.resolve_punch(
                record.source_player, record.punch, record.intensity, landed)
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
            if await send_bounded(websocket, encode(record.final_event)):
                await send_bounded(websocket, encode(self.state()))

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
                await send_bounded(websocket, encode(self.welcome(player_id)))
                self.ready[player_id] = websocket
                self.engine.set_connected(player_id, True)
                if self.auto_start and len(self.ready) >= self.required_players:
                    self.engine.start() or self.engine.resume()
                # Everyone sees the new connected flag; the joiner gets its full state.
                snapshot = encode(self.state())
                await asyncio.gather(*(send_bounded(socket, snapshot)
                                       for socket in self.ready.values()))
            for record in tuple(self.pending.values()):
                if record.source_player == player_id and not record.observation_future.done():
                    await self._send_attempt(record, websocket)
            async for raw in websocket:
                kind = message_type(raw)
                if kind == "PlayerCommand":
                    await self.player_command(player_id, client_id, raw)
                    continue
                if kind == "PickupObservation":
                    await self.pickup_observation(player_id, client_id, raw)
                    continue
                observation = decode_observation(raw) if kind == "PunchObservation" else None
                if observation is None:
                    # Ignore rather than close: one bad message must not drop a player.
                    print(f"[PHONE] P{player_id} ignored unsupported or invalid "
                          f"{kind or 'non-JSON'} message", flush=True)
                    continue
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
        # Each send is bounded, so one stalled phone can't hold up the other.
        await asyncio.gather(*(send_bounded(socket, payload) for socket in sockets))
        return len(sockets)

    async def broadcast_state(self):
        async with self.broadcast_lock:
            self.engine.advance()
            await self._broadcast_transitions_locked()
            return await self.broadcast(self.state())

async def periodic_states(hub, interval_seconds=STATE_INTERVAL_SECONDS):
    while True:
        await asyncio.sleep(interval_seconds)
        await hub.broadcast_state()
