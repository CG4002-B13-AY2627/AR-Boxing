#!/usr/bin/env python3
"""One-process AI -> PunchAttempt -> observation -> final GameEvent WSS demo.

Use --source fake for a no-FPGA end-to-end test, or --source fpga-noise for the
existing seeded-noise model test. Neither source uses live ESP sensor data.
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
    # PYNQ and its dependencies can request asyncio.get_event_loop() during
    # import/Overlay construction. asyncio.to_thread() does not install one.
    # Keep this worker-local loop distinct from the running WSS loop passed in.
    worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker_loop)
    try:
        return _run_model(args, hub, loop, action_map, attack_ids)
    finally:
        try:
            worker_loop.run_until_complete(worker_loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            worker_loop.close()


def _run_model(args, hub, loop, action_map, attack_ids):
    # AI dependencies stay in the group's existing deployment directory.
    # The FPGA driver is constructed and used only by this single worker.
    sys.path.insert(0, str(args.ai_dir / "src"))
    import numpy as np
    from nn_driver import NNDriver
    from postprocess import Postprocess
    from preprocess import Preprocess
    from window import WindowBuffer

    try:
        with NNDriver(run_dir=args.ai_dir) as nn:
            pre = Preprocess(nn.build_dir, desc=nn.desc)
            buffers = [WindowBuffer(nn.desc.window, nn.desc.channels) for _ in range(2)]
            posts = [Postprocess(nn.desc, pre.channel_names) for _ in range(2)]
            print(f"[MODEL] bitstream={nn.bitstream.name} contract={nn.desc}", flush=True)
            print("[TEST] seeded random NOISE; predictions are not real punches", flush=True)
            rng = np.random.default_rng(0)
            windows = events = resolved = 0
            started = time.perf_counter()
            # Reproduce the supplied template's test stream and timestamps.
            # This is deliberately offline noise, not a real-time sample grid.
            for index in range(args.samples):
                player = index % 2
                sample = rng.standard_normal(nn.desc.channels).astype(np.float32) * 4.0
                got = buffers[player].push(sample, index / buffers[0].rate)
                if got is None:
                    continue
                raw, stamp = got
                windows += 1
                _, logits = nn.predict(pre.window(raw))
                for event in posts[player].push(logits, raw, stamp):
                    events += 1
                    # This is the template's sink() handoff: a real Event object
                    # crosses from the model worker to the same-process WSS loop.
                    attack_id = attack_ids.next(player)
                    future = asyncio.run_coroutine_threadsafe(
                        send_ai_demo(hub, player, event, action_map,
                                     args.demo_intensity, args.response_timeout_ms,
                                     attack_id), loop)
                    resolved += future.result(timeout=10) is not None
            print(f"[DONE] {windows} windows, {events} AI events, "
                  f"{resolved} resolved attacks, {time.perf_counter() - started:.2f}s", flush=True)
    except SystemExit as exc:
        raise RuntimeError(f"AI driver/configuration stopped: {exc}") from exc


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
    parser.add_argument("--source", choices=("fake", "fpga-noise"),
                        default="fpga-noise", help="fake needs no FPGA; fpga-noise uses seeded model input")
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
