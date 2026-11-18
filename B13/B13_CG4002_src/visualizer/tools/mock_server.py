"""Development WebSocket authority for the CG4002 iOS visualizer."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import ssl
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve


HEALTH_ITEM_ID = "health-mock-001"
ATTACK_ITEM_ID = "attack-mock-001"


@dataclass
class Simulation:
    """Deterministic authoritative state used by the external mock server."""

    sequence_start: int = 0
    seed: int = 4002
    player_one_health: float = 60.0
    player_two_health: float = 100.0
    attack_interval_seconds: float = 0.0
    health_spawn_seconds: float = 2.0
    health_collect_seconds: float = 6.0
    health_expire_seconds: float = 10.0
    health_magnitude: float = 25.0
    health_distance_metres: float = 1.0
    health_bearing_degrees: float | None = None
    health_hand: str | None = None
    auto_collect_health: bool = True
    include_attack_item: bool = False
    attack_item_spawn_seconds: float = 3.0
    attack_item_expire_seconds: float = 8.0
    started_at: float = field(default_factory=time.monotonic)

    event_sequence: int = field(init=False)
    state_sequence: int = field(init=False)
    player_one_attacks: bool = field(default=True, init=False)
    next_attack_seconds: float = field(init=False)
    health_collected: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.validate()
        self.event_sequence = self.sequence_start
        self.state_sequence = self.sequence_start
        self.next_attack_seconds = self.attack_interval_seconds
        rng = random.Random(self.seed)
        if self.health_bearing_degrees is None:
            self.health_bearing_degrees = rng.choice((-40.0, 0.0, 40.0))
        if self.health_hand is None:
            self.health_hand = "LEFT" if self.health_bearing_degrees <= 0 else "RIGHT"

    def validate(self) -> None:
        if self.sequence_start < 0:
            raise ValueError("sequence start must be non-negative")
        if not 0.0 <= self.player_one_health <= 100.0:
            raise ValueError("player-one health must be in [0, 100]")
        if not 0.0 <= self.player_two_health <= 100.0:
            raise ValueError("player-two health must be in [0, 100]")
        if self.attack_interval_seconds < 0.0:
            raise ValueError("attack interval must be non-negative")
        if self.health_spawn_seconds < 0.0:
            raise ValueError("health spawn time must be non-negative")
        if self.health_collect_seconds <= self.health_spawn_seconds:
            raise ValueError("health collection must occur after spawn")
        if self.health_expire_seconds <= self.health_spawn_seconds:
            raise ValueError("health expiry must occur after spawn")
        if not 0.0 <= self.health_magnitude <= 100.0:
            raise ValueError("health magnitude must be in [0, 100]")
        if not 0.5 <= self.health_distance_metres <= 2.0:
            raise ValueError("health distance must be in [0.5, 2.0]")
        if self.health_bearing_degrees is not None and not (
            -90.0 <= self.health_bearing_degrees <= 90.0
        ):
            raise ValueError("health bearing must be in [-90, 90]")
        if self.health_hand not in (None, "LEFT", "RIGHT"):
            raise ValueError("health hand must be LEFT or RIGHT")
        if self.include_attack_item:
            if self.attack_item_spawn_seconds < 0.0:
                raise ValueError("attack-item spawn time must be non-negative")
            if self.attack_item_expire_seconds <= self.attack_item_spawn_seconds:
                raise ValueError("attack-item expiry must occur after spawn")

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    @staticmethod
    def server_milliseconds(elapsed_seconds: float) -> int:
        return max(0, int(elapsed_seconds * 1000.0))

    def next_event_sequence(self) -> int:
        value = self.event_sequence
        self.event_sequence += 1
        return value

    def next_state_sequence(self) -> int:
        value = self.state_sequence
        self.state_sequence += 1
        return value

    def advance(self, elapsed_seconds: float) -> list[dict[str, object]]:
        """Apply due authority decisions and return transient events once."""
        events: list[dict[str, object]] = []
        if (
            self.auto_collect_health
            and not self.health_collected
            and self.health_collect_seconds <= elapsed_seconds
            and self.health_collect_seconds < self.health_expire_seconds
        ):
            self.health_collected = True
            self.player_one_health = min(
                100.0, self.player_one_health + self.health_magnitude
            )
            events.append(self.health_pickup_event(elapsed_seconds))

        if self.attack_interval_seconds > 0.0:
            while elapsed_seconds >= self.next_attack_seconds:
                events.append(self.punch_event(self.next_attack_seconds))
                self.next_attack_seconds += self.attack_interval_seconds

        return events

    def health_pickup_event(self, elapsed_seconds: float) -> dict[str, object]:
        return {
            "type": "GameEvent",
            "seq": self.next_event_sequence(),
            "timestamp": self.server_milliseconds(elapsed_seconds),
            "event": "ITEM_PICKUP",
            "source_player": 1,
            "target_player": 1,
            "punch": "",
            "confidence": 1.0,
            "intensity": 0.0,
            "outcome": "NONE",
            "item_id": HEALTH_ITEM_ID,
            "item_type": "HEALTH",
            "hand": self.health_hand,
        }

    def punch_event(self, elapsed_seconds: float) -> dict[str, object]:
        source, target = ((1, 2) if self.player_one_attacks else (2, 1))
        if target == 1:
            self.player_one_health = max(0.0, self.player_one_health - 7.0)
        else:
            self.player_two_health = max(0.0, self.player_two_health - 7.0)

        message: dict[str, object] = {
            "type": "GameEvent",
            "seq": self.next_event_sequence(),
            "timestamp": self.server_milliseconds(elapsed_seconds),
            "event": "PUNCH",
            "source_player": source,
            "target_player": target,
            "punch": "LEFT_HOOK" if source == 1 else "CROSS",
            "confidence": 0.94,
            "intensity": 0.81,
            "outcome": "HIT",
        }
        self.player_one_attacks = not self.player_one_attacks
        return message

    def state(self, elapsed_seconds: float) -> dict[str, object]:
        active_items: list[dict[str, object]] = []
        if self.health_is_active(elapsed_seconds):
            active_items.append(
                {
                    "id": HEALTH_ITEM_ID,
                    "item_type": "HEALTH",
                    "owner_player": 1,
                    "distance_m": self.health_distance_metres,
                    "bearing_degrees": self.health_bearing_degrees,
                    "magnitude": self.health_magnitude,
                    "remaining_ms": self.remaining_milliseconds(
                        self.health_expire_seconds, elapsed_seconds
                    ),
                }
            )
        if self.attack_item_is_active(elapsed_seconds):
            active_items.append(
                {
                    "id": ATTACK_ITEM_ID,
                    "item_type": "ATTACK_BOOST",
                    "owner_player": 1,
                    "distance_m": 1.1,
                    "bearing_degrees": 35.0,
                    "magnitude": 1.25,
                    "remaining_ms": self.remaining_milliseconds(
                        self.attack_item_expire_seconds, elapsed_seconds
                    ),
                }
            )

        return {
            "type": "MatchState",
            "seq": self.next_state_sequence(),
            "timestamp": self.server_milliseconds(elapsed_seconds),
            "player_1": {"health": self.player_one_health, "stamina": 75.0},
            "player_2": {"health": self.player_two_health, "stamina": 68.0},
            "round_time": max(0.0, 90.0 - elapsed_seconds),
            "state": "FIGHTING",
            "active_items": active_items,
        }

    def health_is_active(self, elapsed_seconds: float) -> bool:
        return (
            self.health_spawn_seconds <= elapsed_seconds < self.health_expire_seconds
            and not self.health_collected
        )

    def attack_item_is_active(self, elapsed_seconds: float) -> bool:
        return (
            self.include_attack_item
            and self.attack_item_spawn_seconds
            <= elapsed_seconds
            < self.attack_item_expire_seconds
        )

    @staticmethod
    def remaining_milliseconds(expires_at: float, elapsed_seconds: float) -> int:
        return max(0, min(120_000, int((expires_at - elapsed_seconds) * 1000.0)))


@dataclass
class DeliveryOptions:
    duplicate_once: bool = False
    stale_once: bool = False
    burst_size: int = 0
    duplicate_sent: bool = False
    stale_sent: bool = False
    burst_sent: bool = False
    previous_state: dict[str, object] | None = None

    def build_messages(
        self, simulation: Simulation, elapsed_seconds: float
    ) -> list[dict[str, object]]:
        events = simulation.advance(elapsed_seconds)
        current_state = simulation.state(elapsed_seconds)
        messages: list[dict[str, object]] = list(events)
        pickup_due = any(message.get("event") == "ITEM_PICKUP" for message in events)
        duplicate_this_batch = (
            pickup_due and self.duplicate_once and not self.duplicate_sent
        )

        if duplicate_this_batch:
            pickup = next(
                message for message in events if message.get("event") == "ITEM_PICKUP"
            )
            messages.append(deepcopy(pickup))
            self.duplicate_sent = True

        messages.append(current_state)
        if duplicate_this_batch:
            messages.append(deepcopy(current_state))

        if (
            pickup_due
            and self.stale_once
            and not self.stale_sent
            and self.previous_state is not None
        ):
            messages.append(deepcopy(self.previous_state))
            self.stale_sent = True

        if (
            not self.burst_sent
            and simulation.health_is_active(elapsed_seconds)
            and self.burst_size > 0
        ):
            messages.extend(
                simulation.state(elapsed_seconds) for _ in range(self.burst_size)
            )
            self.burst_sent = True

        self.previous_state = deepcopy(current_state)
        return messages


async def handle_client(
    websocket: ServerConnection,
    clients: set[ServerConnection],
    simulation: Simulation,
) -> None:
    # Send a fresh complete state before joining broadcasts. This is the
    # convergence path after a missed transient event or temporary disconnect.
    elapsed = simulation.elapsed_seconds()
    await websocket.send(encode(simulation.state(elapsed)))
    clients.add(websocket)
    print(f"client connected: {websocket.remote_address}")
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)
        print(f"client disconnected: {websocket.remote_address}")


async def broadcast(
    clients: set[ServerConnection],
    simulation: Simulation,
    delivery: DeliveryOptions,
    tick_seconds: float,
) -> None:
    while True:
        messages = delivery.build_messages(simulation, simulation.elapsed_seconds())
        if clients:
            payloads = [encode(message) for message in messages]
            results = await asyncio.gather(
                *(client.send(payload) for client in tuple(clients) for payload in payloads),
                return_exceptions=True,
            )
            if any(isinstance(result, Exception) for result in results):
                # Closed clients are removed by their handlers. Keep the authority
                # loop alive so remaining/reconnecting phones still converge.
                pass
        await asyncio.sleep(tick_seconds)


def encode(message: dict[str, object]) -> str:
    return json.dumps(message, separators=(",", ":"))


def tls_context(cert_path: str | None, key_path: str | None) -> ssl.SSLContext | None:
    if not cert_path and not key_path:
        return None
    if not cert_path or not key_path:
        raise ValueError("--cert and --key must be supplied together")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(Path(cert_path), Path(key_path))
    return context


def build_simulation(args: argparse.Namespace) -> Simulation:
    # A wall-clock-derived default stays monotonic across ordinary process
    # restarts, avoiding rejection by a still-running phone's sequence gates.
    sequence_start = (
        args.sequence_start
        if args.sequence_start is not None
        else default_sequence_start()
    )
    return Simulation(
        sequence_start=sequence_start,
        seed=args.seed,
        player_one_health=args.player_one_health,
        player_two_health=args.player_two_health,
        attack_interval_seconds=args.attack_interval_seconds,
        health_spawn_seconds=args.health_spawn_seconds,
        health_collect_seconds=args.health_collect_seconds,
        health_expire_seconds=args.health_expire_seconds,
        health_magnitude=args.health_magnitude,
        health_distance_metres=args.health_distance_metres,
        health_bearing_degrees=args.health_bearing_degrees,
        health_hand=args.health_hand,
        auto_collect_health=not args.no_auto_collect,
        include_attack_item=args.include_attack_item,
        attack_item_spawn_seconds=args.attack_item_spawn_seconds,
        attack_item_expire_seconds=args.attack_item_expire_seconds,
    )


def default_sequence_start() -> int:
    return int(time.time() * 1000.0)


async def run(args: argparse.Namespace) -> None:
    if args.tick_seconds <= 0.0:
        raise ValueError("--tick-seconds must be greater than zero")
    if args.burst_size < 0:
        raise ValueError("--burst-size must be non-negative")

    clients: set[ServerConnection] = set()
    simulation = build_simulation(args)
    delivery = DeliveryOptions(
        duplicate_once=args.duplicate_once,
        stale_once=args.stale_once,
        burst_size=args.burst_size,
    )
    scheme = "wss" if args.cert else "ws"
    print(
        f"mock server listening on {scheme}://{args.host}:{args.port} "
        f"seed={args.seed} sequence_start={simulation.sequence_start}"
    )
    print(
        "health lifecycle: "
        f"spawn={args.health_spawn_seconds:.2f}s "
        f"collect={'disabled' if args.no_auto_collect else f'{args.health_collect_seconds:.2f}s'} "
        f"expire={args.health_expire_seconds:.2f}s"
    )

    async with serve(
        lambda websocket: handle_client(websocket, clients, simulation),
        args.host,
        args.port,
        ssl=tls_context(args.cert, args.key),
    ):
        await broadcast(clients, simulation, delivery, args.tick_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--cert", help="PEM certificate for optional WSS")
    parser.add_argument("--key", help="PEM private key for optional WSS")
    parser.add_argument("--seed", default=4002, type=int)
    parser.add_argument(
        "--sequence-start",
        type=int,
        help="Deterministic initial event/state sequence; default uses wall-clock ms",
    )
    parser.add_argument("--tick-seconds", default=0.1, type=float)
    parser.add_argument(
        "--attack-interval-seconds",
        default=0.0,
        type=float,
        help="Seconds between punch events; 0 keeps the pickup demo isolated",
    )
    parser.add_argument("--player-one-health", default=60.0, type=float)
    parser.add_argument("--player-two-health", default=100.0, type=float)
    parser.add_argument("--health-spawn-seconds", default=2.0, type=float)
    parser.add_argument("--health-collect-seconds", default=6.0, type=float)
    parser.add_argument("--health-expire-seconds", default=10.0, type=float)
    parser.add_argument("--health-magnitude", default=25.0, type=float)
    parser.add_argument("--health-distance-metres", default=1.0, type=float)
    parser.add_argument("--health-bearing-degrees", type=float)
    parser.add_argument("--health-hand", choices=("LEFT", "RIGHT"))
    parser.add_argument(
        "--no-auto-collect",
        action="store_true",
        help="Leave the health item active until its expiry instead of collecting it",
    )
    parser.add_argument("--include-attack-item", action="store_true")
    parser.add_argument("--attack-item-spawn-seconds", default=3.0, type=float)
    parser.add_argument("--attack-item-expire-seconds", default=8.0, type=float)
    parser.add_argument(
        "--duplicate-once",
        action="store_true",
        help="Repeat the pickup event and its collection state once",
    )
    parser.add_argument(
        "--stale-once",
        action="store_true",
        help="Send the last pre-collection state after the collection state once",
    )
    parser.add_argument(
        "--burst-size",
        default=0,
        type=int,
        help="Extra valid state snapshots sent together when the health item spawns",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        pass
