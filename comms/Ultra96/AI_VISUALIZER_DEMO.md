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

### Tutorial mode (any `--players`, one player at a time)

The phone's **Tutorial** button sends `START_TUTORIAL` from LOBBY:

```
LOBBY --START_TUTORIAL--> CALIBRATING --I'm set--> FIGHTING (no countdown)
FIGHTING --Pause--> PAUSED --Resume--> FIGHTING
any tutorial phase --EXIT_TUTORIAL, or that phone leaves--> LOBBY (new match)
```

`MatchState.mode` is `TUTORIAL` throughout and `tutorial_player` names the
player doing it. The other slot plays a punching
bag: the round clock stops, health refills to 100 instead of a KO, and
punches resolve normally (a punch with the marker out of view still MISSes).
`PRACTICE_PUNCH` makes the bag punch back 1.5 s later (JAB, LEFT_HOOK,
LEFT_UPPERCUT in turn): BLOCK if the player is guarding then, else HIT.
`PRACTICE_ITEM` spawns an attack boost to collect, always 1 m away at -65 degrees (the player's left). On a two-player server the
other phone waits in its lobby; its commands and wearable actions are ignored
and its leaving never pauses the tutorial. When the tutorial ends, the other
player can start theirs, then both press Ready for a match, all without a
restart. Rules:
CG4002-Viz `docs/protocol.md`, "Tutorial mode".

### God mode for demo play

Add `--god-mode` when launching `esp_ai_live_dashboard.py`, `esp_ai_live.py`
or `ai_to_visualizer_demo.py`. It is off by default: omit the flag for full
play with normal KO and round-time endings. Restart the server to change it.

God mode protects **both** players: damage reduces HP to a minimum of 1 and
the round timer stays at its configured starting value. HIT/BLOCK/MISS,
tracking checks, stamina costs and regeneration, attack cooldowns, guards,
pickups and their fight-time expiry still work. Damage events report actual
HP lost (possibly 0 at the floor). Pausing, disconnects and the normal
Ready/calibration flow still apply. To finish a demo, pause and return to
the lobby with Restart match, or stop the server with Ctrl+C.

The launch setting survives Restart match and tutorial exit. Tutorial keeps
its existing refill-to-100 rule. No phone message fields or mode names change;
the phone does not need a new button. The server prints `[GAME] God mode ON`
or `OFF`; the live dashboard also shows it in the MATCH card and `/api/status`
JSON (`god_mode`). The phone will display a frozen round timer during God mode.

**Ultra96**, after deploying these modified files into the repository:

```sh
cd /home/xilinx/AR-Boxing/comms/Ultra96
sudo -E python3 esp_ai_live_dashboard.py \
  --mode fpga \
  --ai-dir /home/xilinx/ai/integration-check \
  --cert /home/xilinx/comms/server.crt \
  --key /home/xilinx/comms/server.key \
  --phone-cert /home/xilinx/comms/server.crt \
  --phone-key /home/xilinx/comms/server.key \
  --wait-players 2 --round-seconds 300 --show-samples --god-mode
```

The existing `live_alignment.py`, AI deployment and trusted certificates must
be available on the board as before. Use `--wait-players 1` for one phone.

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
| `w` | Weave: 3 s invincible to punches (35 stamina, no regen, 4 s cooldown) |
| `i` | Spawn a health pack for the selected player |
| `o` | Spawn an attack boost for the selected player |
| `k` | Pickup: the selected player's phone is asked for its reach |
| `p` | Operator pause |
| `n` | New match: back to LOBBY from any phase |
| `s` | Print and broadcast the current state |
| `r` | Retry the last action with the same ID (must not apply twice) |
| `?`, `q` | Help, quit |

The server never decides hit or reach itself from the keyboard: a punch waits
for the attacker's phone (`PunchAttempt` -> `PunchObservation`: AprilTag seen
or not, 750 ms, timeout = miss); a pickup waits for the owner's phone
(`PickupCheck` -> `PickupObservation`: distance to the item, within 0.5 m).

## Rules

| Punch | Damage at intensity 1 | Stamina | Lock |
|---|---:|---:|---:|
| Jab | 5 | 8 | 0.5 s |
| Cross | 7 | 10 | 0.5 s |
| Hook | 10 | 15 | 0.7 s |
| Uppercut | 15 | 22 | 1.0 s |

- Damage = base x `--demo-intensity` (default 0.6) x the attacker's attack
  multiplier (1.5 while boosted, else 1), x 0.3 if the target is guarding when
  the punch resolves, capped by remaining health. Not tracked
  = miss, no damage. A punch still pending across a pause misses.
- Stamina regenerates at 12/s while fighting. An attack is refused (no
  `PunchAttempt`) outside FIGHTING, during the previous animation or guard, or
  without enough stamina.
- Round: 90 s (`--round-seconds`). Result at MATCH_END: higher health wins,
  equal is a draw.
- Pickups: one item per player at a time (health pack or attack boost), 1 m
  away at a random bearing within +/-65 deg, 30 s of fight time to collect
  (frozen while paused). Spawned by `i` (health) / `o` (attack boost), or
  `--spawn-seconds N` for every connected phone while fighting: health when the
  player is below 50 HP, otherwise health and attack boost alternate. Cleared at
  ROUND_END. The live servers (`esp_ai_live.py`, `esp_ai_live_dashboard.py`)
  take the same `--spawn-seconds` (default 0: no pickups).
- Health pack: +25 HP (capped at 100, consumed even at full).
- Attack boost: the collector's punches deal 1.5x damage for 30 s of fight time
  (frozen while paused). MatchState reports `attack_multiplier` and
  `attack_multiplier_remaining_ms`; the `ITEM_PICKUP` event has magnitude 1.5
  and `effect_duration_ms` 30000. Collecting another while boosted resets the
  timer to 30 s (no stacking). Boosts end at ROUND_END and on a new match.
- Weave (CG4002-Viz `docs/protocol.md` "Weave"): costs 35 stamina, makes the
  player invincible to punches for 3 s, and stamina does not regenerate while
  weaving (about 71 stamina in effect). Refused outside FIGHTING, mid-punch,
  while already weaving, during the 4 s cooldown after a weave, or below 35
  stamina. No punching or guarding while weaving; starting one ends a guard.
  A punch that resolves while its target weaves is `DODGE`, 0 damage (the
  tutorial bag's punch too). Emits a `WEAVE` event (`attack_id` = the action
  ID, `effect_duration_ms` 3000); MatchState reports `weave_remaining_ms` and
  `weave_cooldown_ms`. Pause, ROUND_END and a new match clear both.
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
becomes a pickup action, `weave` becomes a weave when its confidence is at
least 0.8 (a false weave is expensive), and `idle`, `use` are ignored.
`--fake-action weave` injects weaves from the fake source.

## Tests

```sh
python -B -m unittest discover -s . -p "test_*.py"
```

Needs `websockets`, and OpenSSL for the TLS tests. When `jsonschema` and a
CG4002-Viz checkout beside AR-Boxing are present (or `CG4002_CONTRACTS_DIR` is
set), every message is also checked against the canonical schemas.
