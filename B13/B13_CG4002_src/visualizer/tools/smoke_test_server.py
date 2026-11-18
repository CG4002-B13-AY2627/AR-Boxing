"""Verify the external mock server's pickup lifecycle and reconnect convergence."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable

import websockets

from mock_server import HEALTH_ITEM_ID


Message = dict[str, object]


def has_item(message: Message, item_id: str) -> bool:
    return message.get("type") == "MatchState" and any(
        item.get("id") == item_id
        for item in message.get("active_items", [])
        if isinstance(item, dict)
    )


def has_converged_collection(
    message: Message, item_id: str, expected_health: float
) -> bool:
    if message.get("type") != "MatchState" or has_item(message, item_id):
        return False
    player = message.get("player_1")
    return isinstance(player, dict) and player.get("health") == expected_health


async def receive_until(
    websocket: object,
    predicate: Callable[[Message], bool],
    deadline: float,
) -> tuple[Message, list[Message]]:
    received: list[Message] = []
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0.0:
            raise TimeoutError("mock-server smoke test timed out")
        payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        message = json.loads(payload)
        received.append(message)
        if predicate(message):
            return message, received


async def run_smoke(args: argparse.Namespace) -> None:
    deadline = asyncio.get_running_loop().time() + args.timeout_seconds

    # The observer remains connected and proves the transient pickup event was
    # emitted. The probe deliberately disconnects and must converge from state.
    async with websockets.connect(args.url) as observer:
        async with websockets.connect(args.url) as probe:
            _, first_probe_messages = await receive_until(
                probe,
                lambda message: has_item(message, args.item_id),
                deadline,
            )

        await asyncio.sleep(args.short_disconnect_seconds)
        async with websockets.connect(args.url) as probe:
            _, second_probe_messages = await receive_until(
                probe,
                lambda message: has_item(message, args.item_id),
                deadline,
            )

        pickup_event, observer_messages = await receive_until(
            observer,
            lambda message: message.get("type") == "GameEvent"
            and message.get("event") == "ITEM_PICKUP"
            and message.get("item_id") == args.item_id,
            deadline,
        )
        collection_state, trailing_messages = await receive_until(
            observer,
            lambda message: has_converged_collection(
                message, args.item_id, args.expected_health
            ),
            deadline,
        )
        observer_messages.extend(trailing_messages)

    # This connection occurs after the observer saw collection. Its first fresh
    # complete snapshot must recover correct health without the missed event.
    async with websockets.connect(args.url) as probe:
        reconnect_state, reconnect_messages = await receive_until(
            probe,
            lambda message: has_converged_collection(
                message, args.item_id, args.expected_health
            ),
            deadline,
        )

    kinds = {message.get("type") for message in observer_messages}
    if kinds != {"GameEvent", "MatchState"}:
        raise RuntimeError(f"expected both message types, received {sorted(kinds)}")

    print(
        "mock-server smoke passed: "
        f"spawn reconnects={len(first_probe_messages)}/{len(second_probe_messages)}, "
        f"pickup event seq={pickup_event['seq']}, "
        f"collection state seq={collection_state['seq']}, "
        f"post-collection reconnect seq={reconnect_state['seq']}, "
        f"reconnect messages={len(reconnect_messages)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--item-id", default=HEALTH_ITEM_ID)
    parser.add_argument("--expected-health", default=85.0, type=float)
    parser.add_argument("--timeout-seconds", default=15.0, type=float)
    parser.add_argument("--short-disconnect-seconds", default=0.2, type=float)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_smoke(parse_args()))
