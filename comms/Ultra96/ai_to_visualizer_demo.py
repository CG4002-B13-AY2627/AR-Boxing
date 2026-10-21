#!/usr/bin/env python3
"""One-process AI -> PunchAttempt -> observation -> final GameEvent WSS demo.

Use --source keyboard for live, no-FPGA input, --source fake for a scripted
end-to-end test, or --source fpga-noise for the seeded-noise model test.
None of these sources uses live ESP sensor data.
The final GameEvent carrying the attack_id acknowledges the observation;
MatchState follows it on both phones. Only this process should bind port 8889.
"""

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import ssl
import sys
import threading
import time
import traceback
import uuid

import websockets
from game_engine import GameEngine
from visualizer_protocol import MAX_MESSAGE_BYTES, PUNCHES, PhoneHub, periodic_states


DEFAULT_ACTION_MAP = {"l_hook": "LEFT_HOOK", "r_hook": "RIGHT_HOOK"}


@dataclass(frozen=True)
class FakeAiEvent:
    """Model-shaped event for testing the real attack path without PYNQ."""

    action: str
    t: float
    confidence: float
    intensity: float = 0.0
    edge: str = None


class AttackIds:
    """Assign one stable ID per classified event; reuse it on a retry."""

    def __init__(self, run_id=None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.counter = 0

    def next(self, player):
        self.counter += 1
        return f"ai-{self.run_id}-p{player + 1}-{self.counter}"


async def send_ai_demo(hub, player, event, action_map, demo_intensity,
                       response_timeout_ms=750, attack_id=None):
    """Map one AI event into the hub's authoritative request/resolve path."""
    if player not in (0, 1):
        raise ValueError("AI player must be 0 or 1")
    print(f"[AI RAW] player={player} action={event.action} "
          f"sample_t={event.t:.3f}s confidence={event.confidence:.3f} "
          f"intensity={event.intensity:.3f} m/s^2 edge={event.edge}", flush=True)
    punch = action_map.get(event.action)
    if event.edge is not None or punch is None:
        print("[AI SKIP] sustained/unmapped action; no punch invented", flush=True)
        return None
    if attack_id is None:
        raise ValueError("a stable attack_id is required for each AI event")
    duplicate = attack_id in hub.attacks
    print(f"[AI REQUEST] attack_id={attack_id} P{player + 1} {punch} "
          f"demo_intensity={demo_intensity}", flush=True)
    final = await hub.request_punch(
        player + 1, punch, float(event.confidence), demo_intensity,
        response_timeout_ms=response_timeout_ms, attack_id=attack_id,
    )
    if final is None:
        print(f"[AI SKIP] attack_id={attack_id} rejected by Game Engine "
              "(lobby, paused, animation, guard, or stamina)", flush=True)
        return None
    label = "AI CACHED" if duplicate else "AI FINAL"
    print(f"[{label}] attack_id={attack_id} seq={final['seq']} "
          f"{final['outcome']} damage={final['damage']}; "
          "PhoneHub owns GameEvent + MatchState delivery", flush=True)
    return final


def run_model(args, hub, loop, action_map, attack_ids):
    # AI dependencies stay in the group's existing deployment directory.
    # The Classifier owns the FPGA driver, so it is built and used only here.
    sys.path.insert(0, str(args.ai_dir / "src"))
    import numpy as np
    from classifier import Classifier

    with Classifier(args.ai_dir) as ai:
        print(f"[MODEL] {ai}", flush=True)
        print("[TEST] seeded random NOISE; predictions are not real punches", flush=True)
        rng = np.random.default_rng(0)
        events = resolved = 0
        started = time.perf_counter()
        # Reproduce the supplied template's test stream and timestamps.
        # This is deliberately offline noise, not a real-time sample grid.
        for index in range(args.samples):
            player = index % 2
            sample = rng.standard_normal(ai.channels).astype(np.float32) * 4.0
            for event in ai.push(player, sample, index / ai.rate):
                events += 1
                # This is the template's sink() handoff: a real Event object
                # crosses from the model worker to the same-process WSS loop.
                attack_id = attack_ids.next(player)
                future = asyncio.run_coroutine_threadsafe(
                    send_ai_demo(hub, player, event, action_map,
                                 args.demo_intensity, args.response_timeout_ms,
                                 attack_id), loop)
                resolved += future.result(timeout=10) is not None
        print(f"[DONE] {ai.windows} windows, {events} AI events, "
              f"{resolved} resolved attacks, {time.perf_counter() - started:.2f}s", flush=True)


async def run_fake(args, hub, action_map, attack_ids):
    """Inject model-shaped events; the phone must still supply its observation."""
    player = args.fake_player - 1
    for index in range(args.fake_count):
        if args.fake_defender_guard:
            guard_id = attack_ids.next(1 - player)
            guard = await hub.request_guard(3 - args.fake_player, guard_id=guard_id)
            print(f"[FAKE GUARD] P{3 - args.fake_player} "
                  f"{'started' if guard else 'rejected'} id={guard_id}", flush=True)
        action = "FAKE_PUNCH" if args.fake_punch else args.fake_action
        event = FakeAiEvent(action, time.monotonic(), args.fake_confidence)
        attack_id = attack_ids.next(player)
        final = await send_ai_demo(hub, player, event, action_map,
                                   args.demo_intensity, args.response_timeout_ms,
                                   attack_id)
        if args.fake_retry and final is not None:
            seq, health = hub.event_seq, dict(hub.health)
            cached = await send_ai_demo(hub, player, event, action_map,
                                        args.demo_intensity, args.response_timeout_ms,
                                        attack_id)
            if cached != final or hub.event_seq != seq or hub.health != health:
                raise RuntimeError("retry changed a resolved attack")
            print(f"[AI RETRY] attack_id={attack_id} returned cached result; "
                  "no second event or damage", flush=True)
        if index + 1 < args.fake_count:
            await asyncio.sleep(args.fake_interval)
    print(f"[DONE] {args.fake_count} fake AI event(s) processed", flush=True)


class KeyboardInput:
    """Forward terminal keys to the asyncio loop without blocking WSS traffic."""

    def __init__(self, queue):
        self.queue = queue
        self.loop = asyncio.get_running_loop()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=0.5)

    def _emit(self, key):
        def enqueue():
            if not self.queue.full():
                self.queue.put_nowait(key.lower())
        try:
            self.loop.call_soon_threadsafe(enqueue)
        except RuntimeError:  # event loop already closed during shutdown
            pass

    def _read(self):
        try:
            self._read_keys()
        except Exception as exc:
            print(f"[KEYS ERROR] terminal input unavailable: {exc}",
                  file=sys.stderr, flush=True)
            self._emit("q")

    def _read_keys(self):
        if not sys.stdin.isatty():
            # Piped input is useful for automated smoke tests; one command per
            # line, followed by Enter. EOF shuts the server down cleanly.
            while not self.stop.is_set():
                line = sys.stdin.readline()
                if not line:
                    self._emit("q")
                    return
                for key in line.strip():
                    self._emit(key)
            return
        if sys.platform == "win32":
            import msvcrt
            while not self.stop.is_set():
                if not msvcrt.kbhit():
                    self.stop.wait(0.05)
                    continue
                key = msvcrt.getwch()
                if key in ("\x00", "\xe0"):
                    msvcrt.getwch()  # discard function/arrow-key suffix
                else:
                    self._emit(key)
            return
        import os
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        original = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self.stop.is_set():
                if select.select([fd], [], [], 0.1)[0]:
                    data = os.read(fd, 1)
                    if not data:
                        self._emit("q")
                        return
                    self._emit(data.decode("utf-8", errors="ignore"))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)


def print_match_state(hub):
    state = hub.engine.snapshot()
    players = []
    for player in (1, 2):
        value = state[f"player_{player}"]
        players.append(f"P{player} HP={value['health']:g} "
                       f"STA={value['stamina']:g} "
                       f"GUARD={'ON' if value['is_blocking'] else 'off'}")
    print(f"[STATE] seq={hub.state_seq} {state['state']} "
          f"time={state['round_time']:g}s | {' | '.join(players)}", flush=True)


async def run_keyboard_commands(args, hub, attack_ids, commands):
    """Run console commands; a queue makes the same path testable without a TTY."""
    selected = 1
    last = None
    print("[KEYS] 1/2 select player | j jab | h hook | u uppercut | "
          "g guard | x end guard | s state | r retry last ID | ? help | q quit",
          flush=True)
    print_match_state(hub)
    while True:
        key = await commands.get()
        if key == "q":
            print("[STOP] keyboard demo closed", flush=True)
            return
        if key == "?":
            print("[KEYS] 1/2 select player | j jab | h hook | u uppercut | "
                  "g guard | x end guard | s state | r retry last ID | ? help | q quit",
                  flush=True)
            continue
        if key in ("1", "2"):
            selected = int(key)
            print(f"[SELECT] player {selected}", flush=True)
            continue
        if key == "s":
            await hub.broadcast_state()
            print_match_state(hub)
            continue
        if key == "r":
            if last is None:
                print("[RETRY] no earlier action", flush=True)
                continue
            kind, player, value, action_id = last
            print(f"[RETRY] {action_id}", flush=True)
        elif key in ("j", "h", "u"):
            kind, player = "punch", selected
            value = {"j": "JAB", "h": "LEFT_HOOK" if player == 1 else "RIGHT_HOOK",
                     "u": "LEFT_UPPERCUT" if player == 1 else "RIGHT_UPPERCUT"}[key]
            action_id = attack_ids.next(player - 1)
            last = kind, player, value, action_id
        elif key in ("g", "x"):
            kind, player, value = "guard", selected, key == "g"
            action_id = attack_ids.next(player - 1)
            last = kind, player, value, action_id
        else:
            if key.strip():
                print(f"[KEYS] unknown key {key!r}; press ? for help", flush=True)
            continue

        if kind == "punch":
            if key != "r":
                print(f"[ATTEMPT] P{player} {value} id={action_id}; "
                      "waiting for phone observation", flush=True)
            event = await hub.request_punch(
                player, value, args.fake_confidence, args.demo_intensity,
                response_timeout_ms=args.response_timeout_ms, attack_id=action_id)
        else:
            print(f"[GUARD] P{player} {'start' if value else 'end'} id={action_id}",
                  flush=True)
            event = await hub.request_guard(
                player, active=value, confidence=args.fake_confidence,
                guard_id=action_id)
        if event is None:
            print("[REJECTED] not fighting, animation/guard active, or "
                  "insufficient stamina", flush=True)
        else:
            print(f"[EVENT] seq={event['seq']} {event['event']} "
                  f"outcome={event.get('outcome', '-')} "
                  f"damage={event.get('damage', 0):g} id={action_id}", flush=True)
        print_match_state(hub)


async def run_keyboard(args, hub, attack_ids):
    commands = asyncio.Queue(maxsize=32)
    keyboard = KeyboardInput(commands)
    keyboard.start()
    try:
        await run_keyboard_commands(args, hub, attack_ids, commands)
    finally:
        keyboard.close()


async def main(args):
    if args.source == "fpga-noise" and not (args.ai_dir / "src").is_dir():
        raise RuntimeError(f"AI src/ directory not found: {args.ai_dir / 'src'}")
    action_map = dict(DEFAULT_ACTION_MAP)
    if args.action_map:
        extra = json.loads(args.action_map.read_text())
        if not isinstance(extra, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or v not in PUNCHES
            for k, v in extra.items()
        ):
            raise ValueError("Action map must map AI label strings to protocol-v2 punch names")
        action_map.update(extra)
    if args.source == "fake":
        if args.fake_punch:
            action_map["FAKE_PUNCH"] = args.fake_punch
        elif args.fake_action not in action_map:
            raise ValueError(f"fake action {args.fake_action!r} is not in the action map")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(args.cert, args.key)
    hub = PhoneHub(engine=GameEngine(round_seconds=args.round_seconds),
                   required_players=args.wait_players)
    attack_ids = AttackIds()

    async def handle(ws):
        print("[PHONE] encrypted connection; awaiting ClientHello", flush=True)
        try:
            await hub.handle(ws)
        finally:
            print("[PHONE] disconnected", flush=True)

    async with websockets.serve(handle, args.host, args.port, ssl=ctx,
                                max_size=MAX_MESSAGE_BYTES):
        state_task = asyncio.create_task(periodic_states(hub))
        try:
            print(f"[WSS] host={args.host} port={args.port} stream={hub.stream_id} "
                  f"source={args.source}", flush=True)
            if args.source == "keyboard":
                print(f"[WAIT] connect {args.wait_players} phone(s); "
                      "commands are available now", flush=True)
                await run_keyboard(args, hub, attack_ids)
            else:
                print(f"[WAIT] connect {args.wait_players} phone(s); complete ClientHello first", flush=True)
                while (len(hub.ready) < args.wait_players or
                       (args.source == "fake" and args.fake_player not in hub.ready)):
                    await asyncio.sleep(0.2)
                print(f"[READY] phone handshake complete; source starts in "
                      f"{args.start_delay:g} seconds", flush=True)
                await asyncio.sleep(args.start_delay)
                if args.source == "fake":
                    await run_fake(args, hub, action_map, attack_ids)
                else:
                    await asyncio.to_thread(
                        run_model, args, hub, asyncio.get_running_loop(), action_map, attack_ids)
                if not args.exit_after_demo:
                    print("[WSS] remains open; Ctrl+C to stop", flush=True)
                    await asyncio.Future()
        finally:
            state_task.cancel()
            await asyncio.gather(state_task, return_exceptions=True)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("keyboard", "fake", "fpga-noise"),
                        default="fpga-noise",
                        help="keyboard and fake need no FPGA; fpga-noise uses seeded model input")
    parser.add_argument("--ai-dir", type=Path, default=Path("/home/xilinx/ai/demo"),
                        help="PYNQ demo directory, used only by fpga-noise")
    parser.add_argument("--cert", type=Path, default=here / "server.crt",
                        help="TLS leaf certificate trusted by each phone")
    parser.add_argument("--key", type=Path, default=here / "server.key",
                        help="matching private key; keep it off Git")
    parser.add_argument("--host", default="0.0.0.0", help="WSS bind address")
    parser.add_argument("--port", type=int, default=8889, help="WSS listen port")
    parser.add_argument("--wait-players", type=int, choices=(1, 2), default=2,
                        help="registered phones required before injection (default: 2)")
    parser.add_argument("--samples", type=int, default=2000,
                        help="seeded-noise samples for fpga-noise source")
    parser.add_argument("--demo-intensity", type=float, default=0.6,
                        help="normalized game intensity, independent of model physical intensity")
    parser.add_argument("--response-timeout-ms", type=int, default=750,
                        help="phone observation deadline in milliseconds (100..2000)")
    parser.add_argument("--round-seconds", type=float, default=90.0,
                        help="single-round duration for timer/round-end tests")
    parser.add_argument("--action-map", type=Path,
                        help="JSON mapping model labels to protocol punch names")
    parser.add_argument("--fake-player", type=int, choices=(1, 2), default=1,
                        help="attacking phone slot for fake source")
    parser.add_argument("--fake-action", default="l_hook",
                        help="AI label to inject; must appear in the action map")
    parser.add_argument("--fake-punch", choices=sorted(PUNCHES),
                        help="protocol punch for synthetic testing, bypassing AI label mapping")
    parser.add_argument("--fake-confidence", type=float, default=0.95)
    parser.add_argument("--fake-count", type=int, default=1,
                        help="number of fake classifications to inject")
    parser.add_argument("--fake-interval", type=float, default=3.0,
                        help="seconds between resolved fake attacks")
    parser.add_argument("--fake-retry", action="store_true",
                        help="retry each attack ID to demonstrate idempotence")
    parser.add_argument("--fake-defender-guard", action="store_true",
                        help="start one timed defender guard before each fake punch")
    parser.add_argument("--start-delay", type=float, default=2.0,
                        help="seconds after phone registration before injection")
    parser.add_argument("--exit-after-demo", action="store_true",
                        help="close WSS after injections; otherwise wait for Ctrl+C")
    args = parser.parse_args()
    args.ai_dir = args.ai_dir.expanduser().resolve()
    if (args.samples < 1 or not 0 <= args.demo_intensity <= 1 or
            not 0 <= args.fake_confidence <= 1 or args.fake_count < 1 or
            args.fake_interval < 0 or args.start_delay < 0 or
            not 0 < args.round_seconds <= 3600 or
            not 100 <= args.response_timeout_ms <= 2000 or
            not 1 <= args.port <= 65535):
        parser.error("invalid sample count, intensity, confidence, timing, port, "
                     "or response timeout (100..2000 ms)")
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n[STOP] output integration test stopped", flush=True)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
