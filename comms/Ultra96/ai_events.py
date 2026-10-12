"""AI action events, delivered to comms by the AI integration (ai-comms-integration).

    import ai_events
    ai_events.subscribe(handler)      # handler(message) is called for every AI event

    message = {
        "player": 1 or 2,
        "action": "l_straight" | "r_straight" | "l_hook" | "r_hook" | "l_uppercut"
                  | "r_uppercut" | "block" | "weave" | "pickup" | "use",
        "edge": None for one-off actions, "start" / "end" for block,
        "t": seconds on this server's clock (from the SENSOR_DATA timestamps),
        "confidence": 0.0 - 1.0,
        "intensity": peak acceleration above gravity, in the units the gloves send,
    }

handler runs on the integration's forwarding thread, so keep it short: hand the
message to your own queue or asyncio loop rather than doing slow work in it.
"""
import threading
import traceback

_lock = threading.Lock()
_handlers = []


def subscribe(handler):
    with _lock:
        _handlers.append(handler)


def publish(message):
    with _lock:
        handlers = list(_handlers)
    for handler in handlers:
        try:
            handler(message)
        except Exception:
            traceback.print_exc()
