# AI-to-visualizer attack-flow demo

This standalone process owns WSS port 8889 and one `GameEngine` match state. Do
not start `game_event_wss_server.py` or `comms_server.py --pipeline` on that
port at the same time. The server now applies prototype rules for lobby,
health, stamina, timed guard, attack pacing, and a single round. Item pickup
and attack-multiplier rules are not yet implemented. `--source fake`
needs no FPGA and injects a model-shaped classified attack. `--source
fpga-noise` runs the existing PYNQ model with seeded random noise, **not**
live ESP32 sensor data.

## Fast local test (Windows Unity Editor)

From `C:\Dev\AR-Boxing`, first run the automated, encrypted two-phone test:

```powershell
python -B -m unittest discover -s comms/Ultra96 -p test_ai_to_visualizer_demo.py -v
```

It creates a temporary test certificate, registers two simulated phone
clients, injects fake AI events, supplies all three observation values, and
checks that both clients receive identical final `GameEvent` and `MatchState`
messages, including a blocked hit. It also checks stable-ID retries,
disconnect/pause/reconnect, and both attacker slots. OpenSSL and the Python
`websockets` package are required. Run all rule and transport tests with
`python -B -m unittest discover -s comms/Ultra96 -p 'test_*.py' -v`.

For an interactive Unity test, start **only** this server (substitute the
certificate/key paths you already use for local WSS):

```powershell
python comms/Ultra96/ai_to_visualizer_demo.py --source fake --host 127.0.0.1 --port 8889 --cert .\comms\Ultra96\wss-certs\server.crt --key .\comms\Ultra96\wss-certs\server.key --wait-players 1 --fake-player 1 --fake-action l_hook --response-timeout-ms 2000 --start-delay 5 --fake-retry
```

In Unity Play Mode, select `NetworkRuntime` in the Hierarchy. On `Game Network
Client`, set `Server Url` to `wss://127.0.0.1:8889`, `Requested Player Id` to
`1`, and enable `Connect On Enable`. Disable `Mock Game Event Source`. The
server waits for this phone's completed `ClientHello`, then waits five seconds
before injecting the fake AI classification. The Editor machine must trust
the certificate issuer, and the certificate must include the host used in the
URL. Copying a PEM file into Unity Assets does not make the OS trust it. Never
turn off certificate validation to make a demo connect.

Watch the server log and Unity `NET LOG`:

1. `ServerWelcome` and initial `MatchState` complete registration.
   With `--wait-players 2`, the first phone sees `LOBBY` until both register;
   then both receive `FIGHTING` snapshots. With `--wait-players 1`, one phone
   is sufficient for local testing.
2. `[AI REQUEST]` creates one `PunchAttempt` sent only to player 1. The local
   glove presentation may start, but no health changes yet.
3. Unity samples `OpponentTargetProvider` and sends `PunchObservation`.
4. `[AI FINAL]` reports the resolved `GameEvent`. Its matching `attack_id` is
   the gameplay acknowledgement; there is no separate `PunchAck` wire type.
5. The server sends that same final event and then a `MatchState` to every
   registered phone. The Game Engine charges attack stamina when accepting the
   attempt, and changes health only after resolving the observation. Unity
   displays the next authoritative snapshot; it never computes damage.
6. With `--fake-retry`, the demo submits the *same* classified event and
   `attack_id` once more. The server returns its cached result without another
   attempt, broadcast, or damage application.

For a two-phone demonstration, set `--wait-players 2` (the default), connect
player 1 and player 2 with distinct `client_id` values, and keep both open.
Only player 1 replies to the attempt; both see the same final outcome/state.
If using real iPhones, use a reachable hotspot/tunnel address in `Server Url`
and a certificate trusted on each iPhone with that address in its SAN. Do not
use `127.0.0.1` on a physical phone; that would mean the phone itself.

## Prototype game rules and simulation controls

The server owns a 90-second single round. It starts in `LOBBY`, enters
`FIGHTING` when the required phone slots register, pauses the timer on a
disconnect, and resumes on the same `client_id` reconnect. Timer expiry or a
knockout enters `ROUND_END`; after two seconds it enters `MATCH_END`.
`ROUND_TRANSITION` events and complete `MatchState` snapshots announce both
end states. No further attacks or guards are accepted outside `FIGHTING`.

| Punch | Base damage at intensity 1 | Stamina cost | Animation lock |
|---|---:|---:|---:|
| Jab | 5 | 8 | 0.5 s |
| Cross | 7 | 10 | 0.5 s |
| Hook | 10 | 15 | 0.7 s |
| Uppercut | 15 | 22 | 1.0 s |

Actual damage is `base × normalized intensity`, capped by remaining health.
Stamina passively regenerates at 12 points/s during `FIGHTING`, to a maximum
of 100. An attack is ignored without a `PunchAttempt` if its player is still
in the prior animation, guarding, out of stamina, or not fighting. Accepted
stamina is charged only once; a repeated ID cannot apply another hit. Guard
costs 8 stamina, lasts at most one second, cannot start during an attack, and
reduces tracked-punch damage to 30%. Guard end can clear it earlier. The
server samples guard status at punch **resolution**, not at request time.

To see a blocked hit in Unity, append `--fake-defender-guard` to the local
command above and keep the tag visible. The server creates a guard for the
other player immediately before the fake attack. For a quick timer/round-end
test, append `--round-seconds 8` and watch the HUD countdown and final state.
To compare jab, hook, and uppercut directly without assuming AI class labels,
run separate fake sessions with `--fake-punch JAB`, `--fake-punch LEFT_HOOK`,
and `--fake-punch LEFT_UPPERCUT`. This override applies **only** to the fake
source; real model labels still require an agreed `--action-map`.
For an attack-pacing demonstration, use `--fake-count 3 --fake-interval 0`; a
fast-responding phone should cause attempts inside the 0.7-second hook lock
to be skipped. This depends on actual reply timing, so the deterministic
`test_game_engine.py` is the reliable cooldown/stamina test.

## Exercise all three tracking results

Use `--fake-count 3 --fake-interval 5` for three attacks in one match, allowing
five seconds between resolved attacks. In XR Simulation, arrange the ID 0
AprilTag marker to be visible for the first, hidden/lost for the second, and
disable/unavailable tracking for the third. The phone's automatic replies are
`TARGET_TRACKED`, `TARGET_NOT_TRACKED`, and `TRACKING_UNAVAILABLE`. The server
resolves these to `HIT`, `MISS`, and `MISS` when the target is not blocking.
The automated test above covers all three without timing-dependent manual
steps. For a simple single attempt, keep the default `--fake-count 1`; use
`--exit-after-demo` to close the WSS server automatically after it resolves.

## FPGA noise source and configuration

On Ultra96, run this **instead of** the other port-8889 servers:

```sh
python3 ai_to_visualizer_demo.py --source fpga-noise --ai-dir /home/xilinx/ai/demo --cert /path/to/server.crt --key /path/to/server.key --wait-players 2
```

The model produces `postprocess.Event` objects. The adapter maps a supported
action to a protocol punch, assigns one stable ID for that classified event,
then calls `PhoneHub.request_punch()`. The WSS loop owns the attack ledger,
observation deadline, and final broadcasts; `GameEngine` owns stamina, guard,
damage, timer, and match phase. The default verified map
is `l_hook -> LEFT_HOOK` and `r_hook -> RIGHT_HOOK`; other model labels are
skipped unless mapped with `--action-map` to one of the protocol punch names.
For example, a JSON map can contain `{"l_jab":"JAB"}` after the team agrees
that the model label means that attack. A sustained/edge event is skipped.

`--demo-intensity` (default `0.6`) is a normalized demo damage input; the
model's physical intensity is logged but is **not** silently converted into
gameplay damage. `--response-timeout-ms` accepts 100–2000 (default 750), and
`--fake-player`, `--fake-action`, `--fake-confidence`, `--fake-count`,
`--fake-punch`, `--fake-interval`, `--fake-retry`, `--fake-defender-guard`, `--round-seconds`,
`--start-delay`, `--host`, `--port`, `--cert`, `--key`, `--samples`, and
`--action-map` are configurable. Run `--help` for the complete
argument list.

An attack ID is generated once per classified event (`ai-<run>-p<slot>-<n>`) and
reused if that event is retried. In this demo, the attack ledger is in memory
for one process/stream. A process restart creates a new stream and resets the
demo match; durable cross-restart exactly-once guarantees need a persistent
Game Engine ledger and stable upstream IDs.
