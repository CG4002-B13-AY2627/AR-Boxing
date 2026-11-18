# Game-engine-to-visualizer protocol

## Transport

Use one persistent WebSocket connection per phone. Use `ws://` only on a controlled development LAN. Use `wss://` for the integrated/demo system with a certificate the iPhone trusts.

On a new or re-established connection, the sender should immediately send its newest complete `MatchState`. Transient events are not replayed; convergence comes from the snapshot. Sender sequence numbers must remain newer than messages already accepted by a still-running client, including across an ordinary sender-process restart.

The authoritative sender pushes two JSON object types. For the pickup prototype this sender may be the in-app debug source or Python mock server; the production laptop-versus-Ultra96 authority remains an integration decision. Every new message includes an explicit `type` discriminator. The visualizer temporarily accepts the initial-report examples without `type` by inferring the shape.

## `GameEvent`

Transient and sent once for a recognised/resolved action.

```json
{
  "type": "GameEvent",
  "seq": 573,
  "timestamp": 12345678,
  "event": "PUNCH",
  "source_player": 1,
  "target_player": 2,
  "punch": "LEFT_HOOK",
  "confidence": 0.94,
  "intensity": 0.81,
  "outcome": "HIT"
}
```

`timestamp` is the sender's monotonic time in milliseconds. `confidence` and `intensity` are normalized to `[0, 1]`. `outcome` is the game engine's resolved result; the phone must not recompute it.

Initial values:

- `event`: `PUNCH`, `GUARD`, `WEAVE`, `ITEM_PICKUP`, `ROUND_TRANSITION`
- `punch`: `JAB`, `CROSS`, `LEFT_HOOK`, `RIGHT_HOOK`, `LEFT_UPPERCUT`, `RIGHT_UPPERCUT`, or empty for non-punch events
- `outcome`: `HIT`, `BLOCK`, `MISS`, or `NONE`

Unknown values should be logged once and ignored safely, allowing the protocol to evolve.

### Accepted item pickup

The health-only prototype uses an accepted `ITEM_PICKUP` event as the transient cue for glove animation and collection feedback:

```json
{
  "type": "GameEvent",
  "seq": 575,
  "timestamp": 12345800,
  "event": "ITEM_PICKUP",
  "source_player": 1,
  "target_player": 1,
  "punch": "",
  "confidence": 1.0,
  "intensity": 0.0,
  "outcome": "NONE",
  "item_id": "health-0042",
  "item_type": "HEALTH",
  "hand": "LEFT"
}
```

`source_player` is the collecting player and `target_player` is the same player. `item_id` identifies the active item. `hand` is optional and, when present, is `LEFT` or `RIGHT`. `ATTACK_BOOST` is reserved in the contract for later work but has no prototype gameplay effect yet.

Receiving this event must not directly modify health. The event triggers transient presentation only; the following `MatchState` supplies the authoritative health value and active-item set.

## `MatchState`

Authoritative periodic snapshot, initially every 100 ms.

```json
{
  "type": "MatchState",
  "seq": 574,
  "timestamp": 12345700,
  "player_1": { "health": 75, "stamina": 62 },
  "player_2": { "health": 39, "stamina": 81 },
  "round_time": 75.0,
  "state": "FIGHTING"
}
```

Initial `state` values are `LOBBY`, `CALIBRATING`, `COUNTDOWN`, `FIGHTING`, `PAUSED`, `ROUND_END`, and `MATCH_END`.

### Active pickups

`MatchState` may include `active_items`. The field is optional during sender migration; a missing field means no active items. Each snapshot contains the complete current set rather than a partial update:

```json
{
  "type": "MatchState",
  "seq": 576,
  "timestamp": 12345820,
  "player_1": { "health": 60, "stamina": 62 },
  "player_2": { "health": 39, "stamina": 81 },
  "round_time": 74.8,
  "state": "FIGHTING",
  "active_items": [
    {
      "id": "health-0042",
      "item_type": "HEALTH",
      "owner_player": 1,
      "distance_m": 1.0,
      "bearing_degrees": -25.0,
      "magnitude": 25.0,
      "remaining_ms": 8000
    }
  ]
}
```

- IDs are case-sensitive and unique within a snapshot.
- `owner_player` determines which phone renders the item.
- `distance_m` is limited to `0.5-2.0`; the first visual prototype applies a narrower local safe annulus.
- `bearing_degrees` is limited to `-90` (left) through `+90` (right), with `0` meaning forward in the local placement frame.
- `magnitude` is descriptive presentation data. The phone must not add it to health locally.
- `remaining_ms` is the sender's remaining lifetime at the snapshot time, avoiding direct comparison between device clocks.
- A snapshot contains at most eight active items.
- `HEALTH` is implemented first. `ATTACK_BOOST` is reserved for a later work package.

## Processing rules

- Parse and validate on the Unity main thread after receiving into a thread-safe queue.
- Drop malformed objects and non-finite/out-of-range values.
- Ignore duplicate or older sequence numbers.
- Limit messages processed per frame so a reconnect burst cannot stall rendering.
- A newer `MatchState` always wins over locally displayed values.
- Keep event and state sequence ordering independent.
- Reject duplicate item IDs, unsupported types, invalid owners, and out-of-range placement/lifetime values.
- Never include credentials, private keys, or certificate material in these JSON objects or in Git.

The schemas under `contracts/` are canonical. Any deviation must be agreed with the communications owner before integration.
