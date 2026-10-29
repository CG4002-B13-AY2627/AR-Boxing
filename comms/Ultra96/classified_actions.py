"""Map classified server inputs to the CPU authority; no sensor dependencies."""
from dataclasses import dataclass
import time
import uuid

# Default boxing convention: left straight -> JAB, right straight -> CROSS.
# Confirm stance with the team; --action-map can override either mapping.
DEFAULT_ACTION_MAP = {
    "l_straight": "JAB", "r_straight": "CROSS",
    "l_hook": "LEFT_HOOK", "r_hook": "RIGHT_HOOK",
    "l_uppercut": "LEFT_UPPERCUT", "r_uppercut": "RIGHT_UPPERCUT",
}
IGNORED_AI_ACTIONS = frozenset({"idle"})
UNIMPLEMENTED_AI_ACTIONS = frozenset({"weave", "use"})


@dataclass(frozen=True)
class FakeAiEvent:
    """Model-shaped event for testing the real attack path without PYNQ."""

    action: str
    t: float
    confidence: float
    intensity: float = 0.0
    edge: str = None


class AttackIds:
    """Assign one stable ID per classified event; reuse it on a retry."""

    def __init__(self, run_id=None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.counter = 0

    def next(self, player):
        self.counter += 1
        return f"ai-{self.run_id}-p{player + 1}-{self.counter}"


async def send_classified_action(hub, player, event, action_map, demo_intensity,
                       response_timeout_ms=750, attack_id=None):
    """Map one AI event into the hub's authoritative request/resolve path."""
    if player not in (0, 1):
        raise ValueError("AI player must be 0 or 1")
    print(f"[AI RAW] player={player} action={event.action} "
          f"sample_t={event.t:.3f}s confidence={event.confidence:.3f} "
          f"intensity={event.intensity:.3f} m/s^2 edge={event.edge}", flush=True)
    if event.action in IGNORED_AI_ACTIONS:
        print(f"[AI IGNORE] {event.action}: no game action", flush=True)
        return None
    if event.action == "pickup":
        if attack_id is None:
            raise ValueError("a stable action ID is required for pickup events")
        return await hub.request_pickup(player + 1, attack_id)
    if event.action in UNIMPLEMENTED_AI_ACTIONS:
        print(f"[AI UNSUPPORTED] {event.action}: current GameEngine has no handler; "
              "no punch/guard invented", flush=True)
        return None
    if event.action == "block":
        if event.edge not in ("start", "end"):
            raise ValueError("block needs edge='start' or 'end'")
        if attack_id is None:
            raise ValueError("a stable action ID is required for block events")
        duplicate = attack_id in hub.guard_actions
        final = await hub.request_guard(
            player + 1, active=event.edge == "start",
            confidence=float(event.confidence), guard_id=attack_id)
        if final is None:
            print(f"[AI GUARD REJECTED] P{player + 1} {event.edge} id={attack_id}", flush=True)
        else:
            label = "AI GUARD CACHED" if duplicate else "AI GUARD"
            print(f"[{label}] P{player + 1} {event.edge} id={attack_id} "
                  f"seq={final['seq']}; MatchState carries is_blocking", flush=True)
        return final
    punch = action_map.get(event.action)
    if event.edge is not None or punch is None:
        print(f"[AI SKIP] {event.action}: unmapped or invalid punch edge; no punch invented", flush=True)
        return None
    if attack_id is None:
        raise ValueError("a stable attack_id is required for each AI event")
    duplicate = attack_id in hub.attacks
    print(f"[AI REQUEST] attack_id={attack_id} P{player + 1} {punch} "
          f"demo_intensity={demo_intensity}", flush=True)
    final = await hub.request_punch(
        player + 1, punch, float(event.confidence), demo_intensity,
        response_timeout_ms=response_timeout_ms, attack_id=attack_id,
    )
    if final is None:
        print(f"[AI SKIP] attack_id={attack_id} rejected by Game Engine "
              "(lobby, paused, animation, guard, or stamina)", flush=True)
        return None
    label = "AI CACHED" if duplicate else "AI FINAL"
    print(f"[{label}] attack_id={attack_id} seq={final['seq']} "
          f"{final['outcome']} damage={final['damage']}; "
          "PhoneHub owns GameEvent + MatchState delivery", flush=True)
    return final
