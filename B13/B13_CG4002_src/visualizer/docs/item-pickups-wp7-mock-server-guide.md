# Item pickups WP7: external mock-server guide

WP7 moves the health-pickup lifecycle out of Unity's disabled development component and into a separate Python WebSocket authority. The Unity client remains receive-only: `ITEM_PICKUP` drives reach/collection presentation, while the following `MatchState` removes the item and changes health.

## Normal Windows simulation

`Main.unity` currently connects to `ws://127.0.0.1:8766`. From the repository root, prepare Python once:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r tools/requirements.txt
```

Start the health-only lifecycle before entering Unity Play Mode:

```powershell
python tools/mock_server.py --host 127.0.0.1 --port 8766
```

The default deterministic schedule is:

- initial player-one health `60`;
- health pickup spawn at `2 s`;
- accepted `ITEM_PICKUP` at `6 s`;
- the same tick's newer `MatchState` removes it and sets health to `85`; and
- expiry at `10 s` if automatic collection is disabled.

The default seed is `4002`. Bearing is deterministically selected from left, centre, or right. Pass `--health-bearing-degrees` and `--health-hand` when a fixed visual direction is required. Run `python tools/mock_server.py --help` for every timing and fault option.

In Unity:

1. Exit Play Mode before changing scene settings. Keep `MockGameEventSource` disabled.
2. Start the Python server and enter Play Mode in `Assets/Scenes/Main.unity`.
3. Focus Game view, hold right mouse, look down, and acquire a floor.
4. Confirm the connection indicator becomes connected.
5. At about two seconds, confirm one health item and one spawn toast.
6. At about six seconds, confirm the requested glove reaches, the item bursts away, the collection toast appears, and authoritative HUD health converges from `60` to `85`.

Do not click **COLLECT NEAREST** for this test. That button belongs to the in-app debug authority; WP7 proves the same presentation path works from an external process.

## Reconnect checks

The server sends a fresh complete `MatchState` immediately whenever a phone connects.

To test reconnect while the authority keeps running, toggle the `GameNetworkClient` component off and on in the Inspector:

1. Disconnect after the item spawns but before six seconds, then reconnect. The item must reappear from the fresh snapshot.
2. Disconnect before six seconds and reconnect after six seconds. The transient event is intentionally missed, but the item must be absent and health must be `85`.
3. Confirm the visible status passes through reconnecting and back to connected.

The server's default sequence base uses wall-clock milliseconds, so an ordinary process restart produces sequence numbers newer than those from the previous process. Passing `--sequence-start` makes tests reproducible, but restarting twice with the same explicit value while Unity remains open will correctly cause the second run's messages to be rejected as stale. The mock server does not persist match state across process restarts; restart is a new simulation, while disconnect/reconnect to a still-running server is the convergence test for one match.

## Automated and fault-injection checks

Run the pure schedule, schema, expiry, burst, and live reconnect tests:

```powershell
py -3 -m unittest tools.test_mock_server -v
py -3 tools/validate_contracts.py
```

With a normal server already running, the smoke client uses one continuous observer plus reconnecting probes. It verifies item recreation before collection, the transient pickup event, and state-only convergence after collection:

```powershell
py -3 tools/smoke_test_server.py --url ws://127.0.0.1:8766
```

For a Unity robustness run, restart the server with deliberate protocol-valid faults:

```powershell
python tools/mock_server.py --host 127.0.0.1 --port 8766 --duplicate-once --stale-once --burst-size 70
```

Expected results:

- the duplicate pickup event does not start a second collection;
- the duplicate collection state is ignored;
- the stale pre-collection state cannot resurrect the item;
- the 70 additional snapshots drain over multiple frames because `MatchController` retains its 64-message per-frame cap; and
- the final HUD/item state still converges.

To test uncollected expiry instead, add `--no-auto-collect`. To include the contract-reserved attack item and verify that it safely expires without a visual/gameplay effect, add `--include-attack-item`; attack-boost presentation remains outside the current prototype scope.

## Transport integration decision

This repository's Unity client uses message-framed WebSockets through `ClientWebSocket`. The current `C:\Dev\cg4002-comms\game_event_server.py` prototype instead uses raw TCP on port `8889` and newline-delimited JSON. They are not wire-compatible: Unity cannot connect directly to that raw TCP socket, and WebSocket frames cannot be consumed as newline-delimited TCP messages.

Before production integration, the communications and visualizer owners must choose one of these explicit options:

1. make the authoritative sender expose the canonical JSON objects over WebSockets; or
2. add a deliberately owned TCP-to-WebSocket gateway.

Do not silently replace Unity's transport, strip WebSocket framing, or run both protocols on the same port. Production/demo WSS still requires an iOS-trusted certificate.
