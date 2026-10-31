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
MATCH_END --every connected phone Play again (RESTART), or nobody left--> LOBBY
PAUSED --any one phone Restart match (RESTART), or the 'n' key--> LOBBY
```

Back to LOBBY is a **new match**: health, stamina, timer and items reset; the
same match_id/stream_id and seq counters continue, item IDs never repeat, a
pending punch can't land and a pending pickup check ends as MATCH_NOT_ACTIVE.

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

**Two iPhones** through the laptop: see the next section.

**Handshake check** against any running server (no game played):

```sh
python -B smoke_test_visualizer_wss.py --url wss://192.168.137.1:8889 --ca ca.crt
```

## Phones, laptop and board

```
iPhone P1 ─┐  laptop Mobile Hotspot        SSH tunnel (bytes only)     Ultra96
iPhone P2 ─┴─> wss://192.168.137.1:8889 ───────────────────────────> 127.0.0.1:8889
```

TLS runs end to end between each phone and the board; the laptop only forwards
bytes. The phones trust a small CA of ours, not the ESP certificate (iOS
rejects that one's 1960-2049 validity).

1. **Certificates, once** (laptop, `pip install cryptography`):

   ```sh
   python comms/Laptop/make_phone_cert.py
   ```

   Writes `ca.crt`, `ca.key`, `server.crt`, `server.key` to
   `comms/.local-certs/phone-wss/` (ignored by Git). The server certificate
   covers `192.168.137.1` and `127.0.0.1` for 397 days; add `--host` for other
   addresses. It refuses to overwrite an existing set.
2. **Board:** copy only `server.crt` and `server.key`
   (`ssh xilinx@<board> mkdir -p certs`, then
   `scp server.crt server.key xilinx@<board>:certs/`).
3. **Each iPhone:** AirDrop or mail `ca.crt`, install the profile, then
   Settings > General > About > Certificate Trust Settings > turn on full
   trust. Only `ca.crt` ever goes on a phone; `ca.key` stays on the laptop.
4. **Run the server on the board**, bound to loopback since only the tunnel
   reaches it:

   ```sh
   python3 ai_to_visualizer_demo.py --host 127.0.0.1 --cert ~/certs/server.crt --key ~/certs/server.key --players 2
   ```

   With the wearables, run `esp_ai_live_dashboard.py` instead (never both) and
   give it the phone pair with `--phone-cert ~/certs/server.crt --phone-key
   ~/certs/server.key`; `--cert`/`--key` stay the ESP certificate.
5. **Laptop:** turn on Mobile Hotspot (gateway `192.168.137.1`), allow
   inbound TCP 8889 in the firewall, and open the tunnel (add
   `-L 0.0.0.0:8888:127.0.0.1:8888` for the ESPs on the live path):

   ```sh
   ssh -N -L 0.0.0.0:8889:127.0.0.1:8889 xilinx@<board>
   ```

6. **Check from the laptop** before touching the phones:

   ```sh
   python comms/Ultra96/smoke_test_visualizer_wss.py --url wss://192.168.137.1:8889 --ca comms/.local-certs/phone-wss/ca.crt
   ```

7. **Phones:** join the hotspot; in the app use `wss://192.168.137.1:8889`,
   P1 on one phone and P2 on the other (until the title card gets its own
   address and P1/P2 setting, set Server Url and Requested Player Id in Main
   before building). Safari to
   `https://192.168.137.1:8889` is a quick trust check: a WebSocket error page
   is fine, a certificate warning means step 3 isn't done.

Never disable certificate validation to make a phone connect, and never commit
or send a `.key` file. The old `Ultra96/wss-certs` keys are in Git history:
don't use them.

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
| `n` | New match: back to LOBBY from any phase |
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
