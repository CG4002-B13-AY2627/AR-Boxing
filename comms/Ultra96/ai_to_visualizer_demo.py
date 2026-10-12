#!/usr/bin/env python3
"""One-process FPGA AI -> protocol-v2 WSS output integration test.

Run from ~/comms, beside visualizer_protocol.py and the existing TLS files:
  sudo -E python3 ai_to_visualizer_demo.py --ai-dir /home/xilinx/ai/demo

Uses the template's seeded NOISE input, not ESP data. Predictions have no game
meaning. Original physical intensity is logged; outgoing intensity is an
explicit fixed demo value. All outgoing punches are MISS with zero damage.
The verified default action map only covers l_hook/r_hook. Other classes are
logged and skipped unless an agreed mapping is supplied with --action-map.
"""

import argparse
import asyncio
import json
from pathlib import Path
import ssl
import sys
import time
import traceback

import websockets
from visualizer_protocol import MAX_MESSAGE_BYTES, PUNCHES, PhoneHub, encode, periodic_states


DEFAULT_ACTION_MAP = {"l_hook": "LEFT_HOOK", "r_hook": "RIGHT_HOOK"}


async def send_ai_demo(hub, player, event, action_map, demo_intensity):
    """Called on the WSS loop; event is the real postprocess.Event object."""
    if player not in (0, 1):
        raise ValueError("AI player must be 0 or 1")
    print(f"[AI RAW] player={player} action={event.action} "
          f"sample_t={event.t:.3f}s confidence={event.confidence:.3f} "
          f"intensity={event.intensity:.3f} m/s^2 edge={event.edge}", flush=True)
    punch = action_map.get(event.action)
    if event.edge is not None or punch is None:
        print("[AI SKIP] sustained/unmapped action; no punch invented", flush=True)
        return 0
    message = hub.demo_punch(player + 1, punch, float(event.confidence), demo_intensity)
    sockets = tuple(hub.ready.values())
    if not sockets:
        print("[AI -> PHONE] no ready phone; event dropped", flush=True)
        return 0
    payload = encode(message)
    results = await asyncio.gather(*(ws.send(payload) for ws in sockets), return_exceptions=True)
    sent = sum(not isinstance(result, BaseException) for result in results)
    print(f"[AI -> PHONE] {sent}/{len(sockets)} sends completed; "
          f"P{player + 1} {punch} seq={message['seq']} "
          f"MISS damage=0 demo_intensity={demo_intensity}", flush=True)
    for result in results:
        if isinstance(result, BaseException):
            print(f"[AI -> PHONE] send error: {result}", flush=True)
    return sent


def run_model(args, hub, loop, action_map):
    # PYNQ and its dependencies can request asyncio.get_event_loop() during
    # import/Overlay construction. asyncio.to_thread() does not install one.
    # Keep this worker-local loop distinct from the running WSS loop passed in.
    worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker_loop)
    try:
        return _run_model(args, hub, loop, action_map)
    finally:
        try:
            worker_loop.run_until_complete(worker_loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            worker_loop.close()


def _run_model(args, hub, loop, action_map):
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
            windows = events = sent = 0
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
                    future = asyncio.run_coroutine_threadsafe(
                        send_ai_demo(hub, player, event, action_map, args.demo_intensity), loop)
                    sent += future.result(timeout=10)
            print(f"[DONE] {windows} windows, {events} AI events, "
                  f"{sent} completed phone sends, {time.perf_counter() - started:.2f}s", flush=True)
            print("[DONE] WSS stays open. Ctrl+C and restart to repeat the model test.", flush=True)
    except SystemExit as exc:
        raise RuntimeError(f"AI driver/configuration stopped: {exc}") from exc


async def main(args):
    if not (args.ai_dir / "src").is_dir():
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
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(args.cert, args.key)
    hub = PhoneHub()

    async def handle(ws):
        print("[PHONE] encrypted connection; awaiting ClientHello", flush=True)
        try:
            await hub.handle(ws)
        finally:
            print("[PHONE] disconnected", flush=True)

    async with websockets.serve(handle, "0.0.0.0", args.port, ssl=ctx,
                                max_size=MAX_MESSAGE_BYTES):
        state_task = asyncio.create_task(periodic_states(hub))
        try:
            print(f"[WSS] port={args.port} stream={hub.stream_id}", flush=True)
            print(f"[WAIT] connect {args.wait_players} phone(s); complete ClientHello first", flush=True)
            while len(hub.ready) < args.wait_players:
                await asyncio.sleep(0.2)
            print("[READY] phone handshake complete; model starts in 2 seconds", flush=True)
            await asyncio.sleep(2)
            await asyncio.to_thread(run_model, args, hub, asyncio.get_running_loop(), action_map)
            await asyncio.Future()
        finally:
            state_task.cancel()
            await asyncio.gather(state_task, return_exceptions=True)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai-dir", type=Path, default=Path("/home/xilinx/ai/demo"))
    parser.add_argument("--cert", type=Path, default=here / "server.crt")
    parser.add_argument("--key", type=Path, default=here / "server.key")
    parser.add_argument("--port", type=int, default=8889)
    parser.add_argument("--wait-players", type=int, choices=(1, 2), default=1)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--demo-intensity", type=float, default=0.6)
    parser.add_argument("--action-map", type=Path)
    args = parser.parse_args()
    args.ai_dir = args.ai_dir.expanduser().resolve()
    if args.samples < 1 or not 0 <= args.demo_intensity <= 1:
        parser.error("samples must be positive; demo intensity must be in [0, 1]")
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n[STOP] output integration test stopped", flush=True)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
