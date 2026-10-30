# Phone game server runbook

`ai_to_visualizer_demo.py` is the phone-facing game server: one process, one
match, WSS port 8889, protocol v2 (contract and rules: CG4002-Viz
`contracts/` and `docs/protocol.md`). `GameEngine` is the authority for phases,
punches, guards, health, stamina, pickups and the result; the phones only
render, send their menu choices (`PlayerCommand`) and answer the server's
tracking checks. The live sensor path (`esp_ai_live.py`,
`esp_ai_live_dashboard.py`) uses the same `PhoneHub`. **Only one process may
bind port 8889.**

## Match flow

```
LOBBY --both Ready--> CALIBRATING --both I'm set--> COUNTDOWN (3 s) --> FIGHTING
FIGHTING --Pause (look down, tap, or 'p') or a phone drops--> PAUSED
PAUSED --both connected and Resume--> COUNTDOWN --> FIGHTING
FIGHTING --KO or round timer--> ROUND_END (2 s) --> MATCH_END (with result)
```

"Both" means `--players` phones connected and every connected phone ready.
Ready flags clear on every phase change. A phone that drops mid-fight pauses
the match; reconnecting never resumes by itself. `--auto-start` restores the old
behaviour (joining starts the fight) for runs without phones' menus.

## Run it

From `C:\Dev\AR-Boxing\comms\Ultra96`.

**Unity Editor, one phone** (plain `ws`, allowed only on 127.0.0.1):

```sh
python -B ai_to_visualizer_demo.py --insecure-ws --host 127.0.0.1 --players 1
```

Unity: Main's Server Url `ws://127.0.0.1:8889`, Play, Start, Ready, I'm set.
Put the URL back to `wss://127.0.0.1:8889` before committing.

**Unity Editor as P1 plus a scripted P2:**

```sh
python -B ai_to_visualizer_demo.py --insecure-ws --host 127.0.0.1 --players 2
python -B smoke_test_visualizer_wss.py --url ws://127.0.0.1:8889 --follow 2
```

The follower presses Ready / I'm set / Resume for P2 and reports every punch
check as "target seen". Stop it with Ctrl+C mid-fight to see the pause.

**Two iPhones** (TLS; each phone must trust the CA, and the leaf certificate's
SAN must include the address the phones use, e.g. `192.168.137.1`):

```sh
python3 ai_to_visualizer_demo.py --cert server.crt --key server.key --players 2
```

Never disable certificate validation to make a phone connect. Never commit or
copy private keys to a phone; only the CA certificate goes on the phone.

**Handshake check** against any running server (no game played):

```sh
python -B smoke_test_visualizer_wss.py --url wss://192.168.137.1:8889 --ca ca.crt
```

## Operator keys (`--source keyboard`, the default)

| Key | Action |
|---|---|
| `1`, `2` | Select the player the next key acts for |
| `j` | Jab |
| `h`, `u` | Hook, uppercut (P1 throws left, P2 right) |
| `g`, `x` | Start or end a guard (1 s, 8 stamina) |
| `i` | Spawn a health pack for the selected player |
| `k` | Pickup: the selected player's phone is asked for its reach |
| `p` | Operator pause |
| `s` | Print and broadcast the current state |
| `r` | Retry the last action with the same ID (must not apply twice) |
| `?`, `q` | Help, quit |

The server never decides hit or reach itself from the keyboard: a punch waits
for the attacker's phone (`PunchAttempt` -> `PunchObservation`: AprilTag seen
or not, 750 ms, timeout = miss); a pickup waits for the owner's phone
(`PickupCheck` -> `PickupObservation`: distance to the pack, within 0.5 m).

## Rules

| Punch | Damage at intensity 1 | Stamina | Lock |
|---|---:|---:|---:|
| Jab | 5 | 8 | 0.5 s |
| Cross | 7 | 10 | 0.5 s |
| Hook | 10 | 15 | 0.7 s |
| Uppercut | 15 | 22 | 1.0 s |

- Damage = base x `--demo-intensity` (default 0.6), x 0.3 if the target is
  guarding when the punch resolves, capped by remaining health. Not tracked
  = miss, no damage. A punch still pending across a pause misses.
- Stamina regenerates at 12/s while fighting. An attack is refused (no
  `PunchAttempt`) outside FIGHTING, during the previous animation or guard, or
  without enough stamina.
- Round: 90 s (`--round-seconds`). Result at MATCH_END: higher health wins,
  equal is a draw.
- Health packs: one per player at a time, 1 m away at a random bearing
  within +/-65 deg, 25 HP (capped at 100, consumed even at full), 30 s of fight
  time (frozen while paused). Spawned by `i`, or `--spawn-seconds N` for every
  connected phone while fighting. Cleared at ROUND_END.
- Every action has a stable ID; a retry replays the cached result and never
  applies twice.

## Other sources

```sh
# Scripted AI-shaped events (no FPGA); waits for FIGHTING, then injects.
python -B ai_to_visualizer_demo.py --insecure-ws --host 127.0.0.1 --players 1 --source fake --fake-count 3 --fake-interval 5
# Seeded noise through the FPGA model on the board (not live sensor data).
python3 ai_to_visualizer_demo.py --source fpga-noise --ai-dir /home/xilinx/ai/demo --cert server.crt --key server.key
```

AI labels map to punches by `DEFAULT_ACTION_MAP` (override with
`--action-map file.json`); `block` start/end edges become guards, `pickup`
becomes a pickup action, and `idle`, `weave`, `use` are ignored.

## Tests

```sh
python -B -m unittest discover -s . -p "test_*.py"
```

Needs `websockets`, and OpenSSL for the TLS tests. When `jsonschema` and a
CG4002-Viz checkout beside AR-Boxing are present (or `CG4002_CONTRACTS_DIR` is
set), every message is also checked against the canonical schemas.
