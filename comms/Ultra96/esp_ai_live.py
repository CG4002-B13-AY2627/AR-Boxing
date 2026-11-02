#!/usr/bin/env python3
"""Experimental fw4 ESP TLS input -> AI worker -> existing GameEngine/WSS.

inspect: validate live alignment, SI units and int8 windows; never infer or punch.
fpga: use the deployed AI code and hardware; damage intensity stays a demo value.
Only one process may own each of ports 8888 and 8889.
"""
import argparse
import asyncio
import concurrent.futures
import contextlib
import json
from pathlib import Path
import queue
import signal
import ssl
import struct
import sys
import threading
import time

import protocol as P
import websockets
from game_engine import GameEngine
from visualizer_protocol import PhoneHub, periodic_states, MAX_MESSAGE_BYTES, PING_INTERVAL_SECONDS
from ai_to_visualizer_demo import send_ai_demo, spawn_items_every, AttackIds, DEFAULT_ACTION_MAP
from live_alignment import Aligner, CHANNELS

# Deliberately a NEW frame type: old timestamps must never silently enter AI.
SYNC_SENSOR = P.SYNC_SENSOR


class Pipeline:
    def __init__(self, args, hub, loop):
        self.args, self.hub, self.loop = args, hub, loop
        self.queue = queue.Queue(maxsize=64)  # bounded latency; never replay backlog
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.counts = dict(pairs=0, windows=0, inferences=0, events=0, queue_drops=0,
                           stale_drops=0, resets=0, event_drops=0)
        self.pending = set()
        self.latest = None
        self.latest_prediction = None
        self.ids = AttackIds()
        self.thread = threading.Thread(target=self.worker, name='single-FPGA-owner', daemon=True)

    def offer(self, player, token, stamp, counts):
        item = (time.monotonic(), player, token, stamp, counts)
        if self.queue.full():
            while True:
                try:
                    self.queue.get_nowait()
                    self.counts['queue_drops'] += 1
                except queue.Empty:
                    break
        self.queue.put_nowait(item)
        self.counts['pairs'] += 1

    def publish(self, player, event):
        # Runs only on asyncio loop; observation waits never block acquisition/infer.
        if len(self.pending) >= 16:
            self.counts['event_drops'] += 1
            return
        if self.hub.engine.phase != 'FIGHTING':
            return
        task = asyncio.create_task(send_ai_demo(
            self.hub, player-1, event, DEFAULT_ACTION_MAP,
            self.args.demo_intensity, 750, self.ids.next(player-1)))
        self.pending.add(task)
        def done(result):
            self.pending.discard(result)
            if not result.cancelled() and result.exception():
                print('[ACTION ERROR]', repr(result.exception()), flush=True)
        task.add_done_callback(done)

    def worker(self):
        worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(worker_loop)
        nn = None
        try:
            sys.path.insert(0, str(self.args.ai_dir / 'src'))
            import numpy as np
            from preprocess import Preprocess
            from window import WindowBuffer
            from postprocess import Postprocess
            from u96_config import SAMPLE_RATE_HZ, WINDOW_STRIDE_SAMPLES
            if self.args.mode == 'fpga':
                from nn_driver import NNDriver
                nn = NNDriver(run_dir=self.args.ai_dir)
                pre = Preprocess(nn.build_dir, desc=nn.desc)
            else:
                pre = Preprocess(self.args.ai_dir / 'bitstream')
            if (pre.channel_names != CHANNELS or pre.desc.channels != 12 or
                    pre.desc.window != 32 or SAMPLE_RATE_HZ != 100 or WINDOW_STRIDE_SAMPLES != 4):
                raise RuntimeError('Live contract requires supplied l_* then r_* channels, 12x32, 100Hz stride4')
            expected = json.loads((Path(__file__).parent / 'expected_norm_stats.json').read_text())
            if not (np.array_equal(pre.mean, np.asarray(expected['mean'], dtype=np.float32)) and
                    np.array_equal(pre.std, np.asarray(expected['std'], dtype=np.float32))):
                raise RuntimeError('Deployed norm_stats differs from the reviewed model; review before running')
            buffers = {p: WindowBuffer(32, 12) for p in (1, 2)}
            posts = {p: Postprocess(pre.desc, pre.channel_names) for p in (1, 2)}
            last = {}
            print('[MODEL]', pre.desc, 'channels=' + ','.join(pre.channel_names), flush=True)
            print('[MODE]', self.args.mode, 'SIMULATED INPUT IS NOT AN ACCURACY TEST', flush=True)
            self.ready.set()
            while not self.stop.is_set():
                try:
                    received, player, token, stamp, counts = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                if time.monotonic() - received > .15:
                    self.counts['stale_drops'] += 1
                    last.pop(player, None)
                    continue
                previous = last.get(player)
                if (previous is None or previous[0] != token or
                        not .009 <= stamp - previous[1] <= .011):
                    buffers[player].reset()
                    posts[player].reset()
                    self.counts['resets'] += 1
                last[player] = (token, stamp)
                si = pre.sample(counts)
                self.latest = (player, stamp, list(counts), si.tolist())
                got = buffers[player].push(si, stamp)
                if got is None:
                    continue
                raw, stamp = got
                quantised = pre.window(raw)
                self.counts['windows'] += 1
                if self.args.mode == 'fpga':
                    label, logits = nn.predict(quantised)
                    self.counts['inferences'] += 1
                    scores = posts[player].scores(logits)
                    self.latest_prediction = (player, stamp, label, float(np.max(scores)))
                    for event in posts[player].push(logits, raw, stamp):
                        self.counts['events'] += 1
                        self.loop.call_soon_threadsafe(self.publish, player, event)
        except BaseException as error:
            self.error = repr(error)
            print('[WORKER ERROR]', self.error, flush=True)
            self.ready.set()
        finally:
            if nn is not None:
                nn.close()
            asyncio.set_event_loop(None)
            worker_loop.close()


class GatewayServer:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.players = set()
        self.aligners = {}
        self.writers = set()
        self.serial = 0
        self.started = time.monotonic()

    async def handle(self, reader, writer):
        player = None
        self.writers.add(writer)
        parser = P.PacketParser()
        align = Aligner()
        self.serial += 1
        connection = self.serial
        session = (connection-1) % 255 + 1
        try:
            # Firmware doesn't send samples until this ACK, so read hello exactly.
            hello = await asyncio.wait_for(reader.readexactly(7), 5)
            packets = parser.feed(hello)
            if len(packets) != 1 or packets[0][0] != P.HANDSHAKE:
                raise ValueError('expected fw4 gateway handshake')
            fields = P.decode(*packets[0])
            if fields['player'] not in (1, 2) or fields['node'] != 2 or fields['fw'] != 4:
                raise ValueError('requires player 1/2, gateway node2, firmware4; flash BOTH new sketches')
            if fields['player'] in self.players:
                raise ValueError('player already connected')
            player = fields['player']
            self.players.add(player)
            self.aligners[player] = align
            writer.write(P.handshake_ack(session, int((time.monotonic()-self.started)*1000)))
            await writer.drain()
            print('[ESP] handshake OK player={} connection={} fw4 TLS'.format(player, connection), flush=True)
            while True:
                data = await asyncio.wait_for(reader.read(4096), 12)
                if not data:
                    break
                for kind, payload in parser.feed(data):
                    if kind == SYNC_SENSOR:
                        p, node, stamp, *axes_epoch = struct.unpack('<BBI6hI', payload)
                        if p != player or node not in (1, 2):
                            raise ValueError('sensor identity mismatch')
                        epoch = axes_epoch.pop()
                        for segment, t, counts in align.push(node, stamp, epoch, axes_epoch):
                            self.pipeline.offer(player, (connection, segment), t, counts)
                    elif kind == P.HEARTBEAT:
                        if P.decode(kind, payload) != dict(player=player, node=2):
                            raise ValueError('heartbeat identity mismatch')
                        writer.write(P.heartbeat_ack(session))
                        await writer.drain()
                    elif kind == P.DISCONNECT:
                        return
                    else:
                        raise ValueError('unexpected frame; raw old SENSOR_DATA must not feed AI')
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError,
                ssl.SSLError, ValueError) as error:
            print('[ESP CLOSE]', str(error), flush=True)
        finally:
            if player is not None:
                self.players.discard(player)
                self.aligners.pop(player, None)
            self.writers.discard(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)
            print('[ESP] disconnected P{} pairs={} alignment_resets={} drops={}'.format(
                player, align.pairs, align.resets, align.drops), flush=True)


async def main(args):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    hub = PhoneHub(engine=GameEngine(round_seconds=args.round_seconds,
                                    god_mode=args.god_mode), required_players=args.wait_players)
    print('[GAME] God mode ' + ('ON: both players minimum 1 HP; round timer frozen'
                               if args.god_mode else 'OFF: normal match rules'), flush=True)
    pipeline = Pipeline(args, hub, loop)
    pipeline.thread.start()
    while not pipeline.ready.is_set():
        if stop.is_set():
            pipeline.stop.set()
            return
        await asyncio.sleep(.1)
    if pipeline.error:
        raise RuntimeError(pipeline.error)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    # Phones need their own certificate (comms/Laptop/make_phone_cert.py): iOS
    # rejects the ESP certificate's 1960-2049 validity.
    phone_tls = tls
    if args.phone_cert:
        phone_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        phone_tls.minimum_version = ssl.TLSVersion.TLSv1_2
        phone_tls.load_cert_chain(args.phone_cert, args.phone_key)
    gateways = GatewayServer(pipeline)
    tick = spawner = None
    try:
        async with await asyncio.start_server(gateways.handle, args.host, 8888, ssl=tls) as esp:
            async with websockets.serve(hub.handle, args.host, 8889, ssl=phone_tls,
                                        max_size=MAX_MESSAGE_BYTES, close_timeout=2,
                                        ping_interval=PING_INTERVAL_SECONDS,
                                        ping_timeout=PING_INTERVAL_SECONDS):
                tick = asyncio.create_task(periodic_states(hub))
                if args.spawn_seconds > 0:
                    spawner = asyncio.create_task(spawn_items_every(hub, args.spawn_seconds))
                print('[READY] ESP TLS:8888 fw4 | phones WSS:8889 | mode=' + args.mode, flush=True)
                previous_pairs = previous_windows = 0
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), 1)
                    except asyncio.TimeoutError:
                        pass
                    if pipeline.error:
                        raise RuntimeError(pipeline.error)
                    c = dict(pipeline.counts)
                    print('[LIVE] pairs_delta={} windows_delta={} totals={} game={}'.format(
                        c['pairs']-previous_pairs, c['windows']-previous_windows, c, hub.engine.phase), flush=True)
                    previous_pairs, previous_windows = c['pairs'], c['windows']
                    if pipeline.latest_prediction:
                        p, t, label, confidence = pipeline.latest_prediction
                        print('[PRED] P{} sample_t={:.3f} top={} confidence={:.3f}'.format(
                            p, t, label, confidence), flush=True)
                    for p, a in tuple(gateways.aligners.items()):
                        print('[ALIGN] P{} pairs={} resets={} discarded={} interpolated_node_samples={}'.format(
                            p, a.pairs, a.resets, a.drops, a.interpolated_axes_groups), flush=True)
                    if args.show_samples and pipeline.latest:
                        p, t, counts, si = pipeline.latest
                        print('[SAMPLE] P{} t={:.3f} counts={} SI={}'.format(
                            p, t, [round(x, 2) for x in counts], [round(x, 5) for x in si]), flush=True)
    finally:
        pipeline.stop.set()
        for task in (tick, spawner):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        for task in tuple(pipeline.pending):
            task.cancel()
        await asyncio.gather(*pipeline.pending, return_exceptions=True)
        for task in tuple(hub.resolver_tasks):
            task.cancel()
        await asyncio.gather(*hub.resolver_tasks, return_exceptions=True)
        for writer in tuple(gateways.writers):
            writer.close()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(
                *(w.wait_closed() for w in tuple(gateways.writers)), return_exceptions=True), 3)
        for _ in range(50):
            if not pipeline.thread.is_alive():
                break
            await asyncio.sleep(.1)
        print('[STOP] live server stopped', flush=True)


if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('inspect', 'fpga'), default='inspect')
    parser.add_argument('--ai-dir', type=Path, default=Path('/home/xilinx/ai/demo'))
    parser.add_argument('--cert', type=Path, default=here / 'server.crt')
    parser.add_argument('--key', type=Path, default=here / 'server.key')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--phone-cert', type=Path,
                        help='phone WSS server.crt from make_phone_cert.py (default: --cert)')
    parser.add_argument('--phone-key', type=Path, help='matching phone WSS server.key')
    parser.add_argument('--wait-players', type=int, choices=(1, 2), default=2)
    parser.add_argument('--round-seconds', type=float, default=90)
    parser.add_argument('--god-mode', action='store_true',
                        help='both players keep at least 1 HP; freeze round timer (default: off)')
    parser.add_argument('--spawn-seconds', type=float, default=0.0,
                        help='spawn a health pack or attack boost for each phone this often '
                             'while FIGHTING (default 0 = no pickups)')
    parser.add_argument('--demo-intensity', type=float, default=.6)
    parser.add_argument('--show-samples', action='store_true')
    args = parser.parse_args()
    if bool(args.phone_cert) != bool(args.phone_key):
        parser.error('--phone-cert and --phone-key go together')
    if args.round_seconds <= 0 or not 0 <= args.demo_intensity <= 1:
        parser.error('invalid round duration/intensity')
    if not 0 <= args.spawn_seconds <= 600:
        parser.error('--spawn-seconds must be 0..600')
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
