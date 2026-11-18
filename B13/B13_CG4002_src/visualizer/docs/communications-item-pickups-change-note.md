# Communications change note: item pickup prototype

## Scope

The visualizer is adding a health-item presentation prototype. Production game-state authority is not selected by this change. The in-app debug source and `tools/mock_server.py` may act as temporary senders; the same wire fields can later be emitted by a laptop or Ultra96 game engine.

The phone remains receive-only for this prototype. It does not send collection attempts or use a collider to award health.

## `MatchState` addition

`active_items` is a new optional array containing the complete active-item set at the snapshot time. A missing field is treated as an empty array during integration.

Initial item fields:

| Field | Meaning |
|---|---|
| `id` | Case-sensitive item identity, unique within the snapshot |
| `item_type` | `HEALTH`; `ATTACK_BOOST` is reserved but not implemented yet |
| `owner_player` | Player `1` or `2`; only that player's phone renders the item |
| `distance_m` | Requested logical distance, bounded to `0.5-2.0` metres |
| `bearing_degrees` | Requested logical bearing from `-90` left to `+90` right |
| `magnitude` | Display metadata; never applied to health by the phone |
| `remaining_ms` | Remaining lifetime relative to this snapshot |

The array is capped at eight items. Duplicate IDs or malformed entries cause the entire snapshot to be rejected.

## `GameEvent` addition

An accepted `ITEM_PICKUP` event requires:

- `item_id` matching an active item;
- `item_type`, initially `HEALTH`; and
- optional `hand`, `LEFT` or `RIGHT`.

`source_player` is the collector and `target_player` is the same player. Existing required fields remain present; the prototype sends an empty `punch`, `confidence: 1.0`, `intensity: 0.0`, and `outcome: NONE`.

The event is a transient animation cue. It does not authorize the phone to modify health. A later `MatchState` removes the item and supplies the new health value.

## Expected sequence

1. A newer `MatchState` includes the health item.
2. The sender accepts collection and emits `ITEM_PICKUP`.
3. A newer `MatchState` omits that ID and contains the resulting health.

Event and snapshot sequence numbers continue to be filtered independently. Repeating the same event or an older snapshot must not award or resurrect an item.

## Compatibility and deferred decisions

- Existing states without `active_items` remain valid during migration.
- Existing punch events are unchanged.
- WP7's external mock authority sends the canonical objects over WebSockets and sends a complete current `MatchState` immediately after each connection so a reconnecting phone can converge without replaying transient events.
- The visualizer WebSocket transport and `cg4002-comms/game_event_server.py` are not currently wire-compatible. The communications prototype uses raw TCP on port `8889` with newline-delimited JSON. Integration must either expose WebSockets at the authority or use an explicitly owned TCP-to-WebSocket gateway; this mock-server work does not silently choose or bridge the production transport.
- The sender's final physical host remains out of scope.
- Phone-to-engine pickup attempts, acknowledgements, attack-boost effects, and proximity validation are deferred.
