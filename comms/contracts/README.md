# CG4002 phone protocol v2 contracts

This directory is the golden wire contract shared by `CG4002-Viz` and
`cg4002-comms`. The visualizer repository is the source of truth. During the
contract-first phase, the complete directory is copied byte-for-byte into the
communications repository so both sides validate the same schemas and examples.

Message direction:

| Message | Direction | Purpose |
|---|---|---|
| `ClientHello` | phone -> Ultra96 | Bind a WebSocket to one player. |
| `ServerWelcome` | Ultra96 -> phone | Confirm protocol, match, stream, and player identity. |
| `PunchAttempt` | Ultra96 -> attacking phone | Request a fresh AR target observation for one classified punch. |
| `PunchObservation` | phone -> Ultra96 | Report tracking evidence, not a hit decision. |
| `PickupCheck` | Ultra96 -> phone | Request proximity evidence after a wearable pickup action. |
| `PickupObservation` | phone -> Ultra96 | Report available distance or unavailable evidence. |
| `PickupResult` | Ultra96 -> requesting phone | Accept or reject that idempotent pickup request. |
| `GameEvent` | Ultra96 -> both phones | Broadcast a final transient outcome for presentation. |
| `MatchState` | Ultra96 -> both phones | Periodically synchronize all recoverable gameplay state. |
| `PlayerCommand` | phone -> Ultra96 | Request a match-flow step (ready, calibrated, pause, resume). Only when the welcome sets `supports_player_commands`. |

Run the self-contained contract suite from the repository root:

```text
python contracts/test_contracts.py
```

Every JSON fixture in `examples/` is golden. Adding a fixture with an unknown
`type`, adding a schema with no fixture, or changing a fixture so it violates
its schema fails the suite. The tests also enforce cross-field rules that JSON
Schema cannot express cleanly, including distinct punch participants and unique
active-item IDs.
