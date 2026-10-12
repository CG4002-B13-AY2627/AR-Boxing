def to_message(player, event):
    return {
        "player": player,
        "action": event.action,
        "edge": event.edge,
        "t": event.t,
        "confidence": event.confidence,
        "intensity": event.intensity,
    }
