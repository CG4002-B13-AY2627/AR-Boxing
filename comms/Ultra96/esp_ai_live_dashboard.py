#!/usr/bin/env python3
"""fw4 ESP TLS input -> deployed model -> existing GameEngine/WSS.

Normalization is loaded from the selected AI build, never from a local copy.
Switch models with --ai-dir; expected_norm_stats.json is not used.
Read-only dashboard: http://127.0.0.1:8890 through SSH forwarding.

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
from ai_to_visualizer_demo import send_ai_demo, AttackIds, DEFAULT_ACTION_MAP
from live_alignment import Aligner, CHANNELS

# Deliberately a NEW frame type: old timestamps must never silently enter AI.
SYNC_SENSOR = P.SYNC_SENSOR


def sensor_si_scale(channel_names):
    """Raw fw4 MPU-6050 counts -> SI; firmware selects +/-2g, +/-250 dps.

    This is a transport/firmware contract, independent of model normalization.
    Both old and new AI preprocessors receive SI, exactly once.
    """
    import numpy as np

    if list(channel_names) != CHANNELS:
        raise RuntimeError('Sensor conversion requires the fw4 l_* then r_* channels')
    accel = 9.80665 / 16384.0
    gyro = np.pi / (180.0 * 131.0)
    return np.asarray([accel] * 3 + [gyro] * 3 +
                      [accel] * 3 + [gyro] * 3, dtype=np.float32)


def validate_model_norm(pre, build_dir, norm_name):
    """Validate the selected build's own stats and the values actually loaded."""
    import numpy as np

    path = (Path(build_dir) / norm_name).resolve()
    stats = json.loads(path.read_text())
    if stats.get('channels') != CHANNELS:
        raise RuntimeError(f'{path}: requires l_* then r_* channel order: {CHANNELS}')
    mean = np.asarray(stats['mean'], dtype=np.float32)
    std = np.asarray(stats['std'], dtype=np.float32)
    if (mean.shape != (12,) or std.shape != (12,) or
            not np.all(np.isfinite(mean)) or not np.all(np.isfinite(std)) or
            not np.all(std > 0)):
        raise RuntimeError(f'{path}: mean/std must have 12 finite values; std must be positive')
    if (list(pre.channel_names) != CHANNELS or
            not np.array_equal(pre.mean, mean) or not np.array_equal(pre.std, std)):
        raise RuntimeError(f"{path}: preprocessing did not load this build's normalization")
    return path


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
        self.dashboard_predictions = {}
        self.dashboard_model = None
        self.dashboard_norm = None
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
            from u96_config import (SAMPLE_RATE_HZ, WINDOW_STRIDE_SAMPLES,
                                   BUILD_DIR_NAME, NORM_STATS_NAME)
            if self.args.mode == 'fpga':
                from nn_driver import NNDriver
                nn = NNDriver(run_dir=self.args.ai_dir)
                pre = Preprocess(nn.build_dir, desc=nn.desc)
            else:
                pre = Preprocess(self.args.ai_dir / BUILD_DIR_NAME)
            if (pre.channel_names != CHANNELS or pre.desc.channels != 12 or
                    pre.desc.window != 32 or SAMPLE_RATE_HZ != 100 or WINDOW_STRIDE_SAMPLES != 4):
                raise RuntimeError('Live contract requires supplied l_* then r_* channels, 12x32, 100Hz stride4')
            build_dir = nn.build_dir if nn is not None else self.args.ai_dir / BUILD_DIR_NAME
            norm_path = validate_model_norm(pre, build_dir, NORM_STATS_NAME)
            si_scale = sensor_si_scale(pre.channel_names)
            buffers = {p: WindowBuffer(32, 12) for p in (1, 2)}
            posts = {p: Postprocess(pre.desc, pre.channel_names) for p in (1, 2)}
            last = {}
            self.dashboard_model = str(pre.desc)
            self.dashboard_norm = str(norm_path)
            print('[MODEL]', pre.desc, 'channels=' + ','.join(pre.channel_names), flush=True)
            print('[AI DIR]', self.args.ai_dir.resolve(), flush=True)
            print('[NORM]', norm_path, '(selected build; no local stats copy)', flush=True)
            print('[SENSOR] fw4 raw counts -> SI on server: 16384 LSB/g, '
                  '131 LSB/(deg/s); AI receives m/s^2 and rad/s', flush=True)
            print('[MODE]', self.args.mode,
                  'ESP live input; real/simulated sensor mode is configured in ESP firmware',
                  flush=True)
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
                counts_array = np.asarray(counts, dtype=np.float32)
                if counts_array.shape != (12,) or not np.all(np.isfinite(counts_array)):
                    raise RuntimeError('ESP sample requires 12 finite raw sensor counts')
                si = counts_array * si_scale
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
                    self.dashboard_predictions[player] = (time.monotonic(), str(label), float(np.max(scores)))
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
        self.monitor = None
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
            if self.monitor:
                self.monitor.gateway_connected(player)
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
                        if self.monitor:
                            self.monitor.sample(player, node)
                        epoch = axes_epoch.pop()
                        for segment, t, counts in align.push(node, stamp, epoch, axes_epoch):
                            if self.monitor:
                                self.monitor.pair(player)
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
            if self.monitor:
                self.monitor.event(f'ESP session P{player}: {error}')
        finally:
            if player is not None:
                if self.monitor:
                    self.monitor.gateway_disconnected(player)
                self.players.discard(player)
                self.aligners.pop(player, None)
            self.writers.discard(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)
            print('[ESP] disconnected P{} pairs={} alignment_resets={} drops={}'.format(
                player, align.pairs, align.resets, align.drops), flush=True)


# Read-only dashboard. HTTP is bound to loopback and accessed through SSH.
from collections import deque

DASHBOARD_HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AR Boxing · Integration Monitor</title>
<style>
:root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#182535;background:#f3f6fa;font-synthesis:none}*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:auto;padding:36px 28px}header{display:flex;justify-content:space-between;align-items:center;gap:20px}h1{font-size:29px;letter-spacing:-1px;margin:8px 0}.eyebrow{font-size:12px;font-weight:700;color:#526c92;letter-spacing:2px}.sub,small{color:#64748b}small{font-size:12px}.banner{background:#e9f7ef;color:#186642;border:1px solid #c3e8d2;border-radius:10px;padding:10px 14px;font-size:13px}.banner.off{background:#fff0ef;color:#ae342a;border-color:#f2c9c5}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0 20px}.metric,.player,.panel{background:white;border:1px solid #dee5ee;border-radius:14px;padding:20px}.metric label{color:#64748b;font-size:12px;display:block}.value{font-size:26px;font-weight:650;margin:9px 0 3px;letter-spacing:-.6px}.players{display:grid;grid-template-columns:1fr 1fr;gap:20px}.ptop{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}h2{font-size:18px;margin:0}h3{font-size:14px;margin:0 0 12px}.optional{font-size:11px;color:#64748b;background:#f1f4f8;padding:5px 9px;border-radius:20px}.row{display:grid;grid-template-columns:1fr auto;gap:7px;padding:13px 0;border-top:1px solid #edf1f5}.row strong{font-size:13px;font-weight:600}.detail{font-size:12px;color:#718096;grid-column:1/-1;line-height:1.5}.badge{font-size:11px;border-radius:20px;padding:4px 9px;white-space:nowrap;align-self:start}.good{background:#e7f7ee;color:#18784b}.warn{background:#fff3da;color:#90620e}.bad{background:#ffedeb;color:#ad392c}.neutral{background:#edf1f6;color:#67788f}.prediction{background:#f4f7fc;padding:14px;border-radius:9px;margin-top:10px;font-size:13px;line-height:1.65}.panel{margin-top:20px}.meta{display:grid;gap:9px;font-family:ui-monospace,Consolas,monospace;font-size:12px;overflow-wrap:anywhere}.events{list-style:none;padding:0;margin:0;font-size:12px;color:#596b80}.events li{padding:8px 0;border-top:1px solid #edf1f5;overflow-wrap:anywhere}.note{font-size:12px;line-height:1.7;color:#6b7c90;margin-top:20px}.sub{font-size:13px;line-height:1.6}footer{margin-top:20px;font-size:11px;color:#8090a2}@media(max-width:760px){main{padding:22px 16px}header{display:block}.banner{margin-top:14px}.metrics{grid-template-columns:1fr 1fr}.players{grid-template-columns:1fr}h1{font-size:25px}}
</style><main><header><div><div class="eyebrow">CG4002 · GROUP B13</div><h1>Integration monitor</h1><div class="sub">Phone connections, hand data and FPGA progress · refreshes every second</div></div><div id="connection" class="banner">Connecting to dashboard…</div></header><div id="content"><div class="panel sub">Waiting for the first server snapshot.</div></div><footer id="updated">Read-only diagnostics · no game controls</footer></main>
<script>
const el=(tag,text,cls)=>{let n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
const age=x=>x===null?'not received':x<1?'< 1 s ago':x.toFixed(1)+' s ago';
function row(title,status,detail){let n=el('div',undefined,'row');n.append(el('strong',title),el('span',status.text,'badge '+status.tone),el('div',detail,'detail'));return n}
function render(s){const root=document.getElementById('content');root.replaceChildren();let metrics=el('section',undefined,'metrics');
for(let [label,value,detail] of [['MATCH',s.game,s.god_mode?'God mode ON · minimum 1 HP · round timer frozen':'God mode OFF · normal match rules'],['PAIRED INPUT',s.pair_rate.toFixed(1)+' /s','left + right aligned samples'],['FPGA INFERENCE',s.inference_rate.toFixed(1)+' /s',s.counts.inferences+' completed · '+s.mode],['DATA DROPS',String(s.counts.queue_drops+s.counts.stale_drops+s.counts.event_drops),'queue / stale / event totals']]){let n=el('div',undefined,'metric');n.append(el('label',label),el('div',value,'value'),el('small',detail));metrics.append(n)}root.append(metrics);
let players=el('section',undefined,'players');for(let p of s.players){let card=el('article',undefined,'player'),top=el('div',undefined,'ptop');top.append(el('h2','Player '+p.id));if(p.optional)top.append(el('span','OPTIONAL SLOT','optional'));card.append(top);
card.append(row('AR phone',p.phone,p.phone_detail),row('Right ESP gateway',p.gateway,p.gateway_detail));
for(let h of p.hands)card.append(row(h.name+' hand data',h.status,h.rate.toFixed(1)+' samples/s · last '+age(h.age)+' · '+h.total+' received'));
card.append(row('Aligned hand pairs',p.pairing,'Last '+age(p.pair_age)+' · '+p.pairs+' pairs · '+p.align_resets+' alignment resets · '+p.discarded+' discarded'));
let pred=p.prediction;card.append(el('div',pred?'Latest prediction: '+pred.label+' · '+(pred.confidence*100).toFixed(1)+'% · '+age(pred.age)+'\nHP '+p.hp+' · stamina '+p.stamina:'No prediction yet · '+(s.mode==='inspect'?'inspect mode does not run inference':'waiting for a complete input window'),'prediction'));players.append(card)}root.append(players);
let panel=el('section',undefined,'panel');panel.append(el('h3','Model & pipeline'));let meta=el('div',undefined,'meta');for(let text of ['AI directory: '+s.ai_dir,'Model: '+(s.model||'not available'),'Normalization: '+(s.norm_path||'not available'),'Worker: '+(s.worker_error?'ERROR — '+s.worker_error:s.worker_alive?'running':'stopped'),'Windows: '+s.counts.windows+' · AI events: '+s.counts.events+' · stream resets: '+s.counts.resets,'WSS sockets: '+s.phone_sockets+' · joined phones: '+s.joined_phones+' / '+s.required_phones])meta.append(el('div',text));panel.append(meta);root.append(panel);
let events=el('section',undefined,'panel');events.append(el('h3','Recent connection events'));let list=el('ul',undefined,'events');for(let event of s.events)list.append(el('li',event.at+' · '+event.message));if(!s.events.length)list.append(el('li','No connection events yet.'));events.append(list);root.append(events);
root.append(el('div','Green hand data means samples arrived within 2 seconds. A gateway connection alone does not prove that both hands are sending. Rates use a rolling 2-second window; counters are cumulative. Pairing is inferred from aligned sample delivery, not a direct ESP sync-valid flag. An idle prediction is normal. ESP real/simulated input is selected in firmware.','note'));
document.getElementById('updated').textContent='Last snapshot '+new Date(s.timestamp*1000).toLocaleTimeString()+' · server uptime '+Math.floor(s.uptime)+' s · read-only diagnostics';}
async function poll(){let box=document.getElementById('connection');try{let r=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(3000)});if(!r.ok)throw Error('HTTP '+r.status);render(await r.json());box.textContent='Dashboard connected';box.className='banner'}catch(e){box.textContent='Dashboard unreachable — check server / SSH tunnel. Values below are stale.';box.className='banner off'}setTimeout(poll,1000)}poll();
</script></html>'''


class Dashboard:
    def __init__(self, pipeline, gateways, hub, args, clock=time.monotonic):
        self.pipeline, self.gateways, self.hub, self.args = pipeline, gateways, hub, args
        self.clock = clock
        self.started = clock()
        self.events = deque(maxlen=16)
        self.phone_sockets = 0
        self.hand = {(p,n): dict(last=None,total=0,times=deque(maxlen=600))
                     for p in (1,2) for n in (1,2)}
        self.connected_at = {}
        self.last_pair = {1:None,2:None}
        self.history = deque([(self.started,0,0)],maxlen=100)
        self._clients = asyncio.Semaphore(16)

    def event(self, message):
        self.events.appendleft(dict(at=time.strftime('%H:%M:%S'),message=str(message)))

    def gateway_connected(self, player):
        self.connected_at[player] = self.clock()
        self.last_pair[player] = None
        for n in (1,2):
            h = self.hand[player,n]
            h['last'] = None
            h['times'].clear()
        self.event(f'P{player} ESP gateway handshake complete')

    def gateway_disconnected(self, player):
        self.connected_at.pop(player,None)
        self.event(f'P{player} ESP gateway disconnected')

    def sample(self, player, node):
        now = self.clock()
        h = self.hand[player,node]
        h['last'] = now
        h['total'] += 1
        h['times'].append(now)

    def pair(self, player):
        self.last_pair[player] = self.clock()

    @staticmethod
    def badge(text, tone):
        return dict(text=text,tone=tone)

    def snapshot(self):
        now = self.clock()
        c = dict(self.pipeline.counts)
        # Keep the history independent of how many browsers poll the page.
        if now-self.history[-1][0] >= .2:
            self.history.append((now,c['pairs'],c['inferences']))
        while len(self.history)>1 and self.history[1][0] < now-2:
            self.history.popleft()
        start,pairs,inferences = self.history[0]
        dt = max(now-start,.001)
        players = []
        for p in (1,2):
            online = p in self.gateways.players
            optional = self.args.wait_players == 1 and p == 2
            if p in self.hub.ready:
                phone = self.badge('Joined','good')
                detail = 'ClientHello accepted; receives server events and state'
            elif p in self.hub.active:
                phone = self.badge('Joining','warn')
                detail = 'Player slot claimed; waiting for handshake completion'
            else:
                phone = self.badge('Not joined','neutral' if optional else 'warn')
                detail = 'Waiting for this player to complete ClientHello'
            hands=[]
            for n,name in ((1,'Left'),(2,'Right')):
                h = self.hand[p,n]
                age = None if h['last'] is None else max(0,now-h['last'])
                while h['times'] and h['times'][0]<now-2:h['times'].popleft()
                rate = len(h['times'])/2.0
                if not online:
                    status = self.badge('Gateway offline','neutral' if optional else 'bad')
                elif age is None:
                    status = self.badge('No samples','warn')
                elif age>2:
                    status = self.badge('Stale / no data','bad')
                else:
                    status = self.badge('Receiving','good')
                hands.append(dict(name=name,age=age,rate=rate,total=h['total'],status=status))
            pair_age = None if self.last_pair[p] is None else max(0,now-self.last_pair[p])
            pairing = self.badge('Flowing','good') if online and pair_age is not None and pair_age<=2 else self.badge('No fresh pairs','neutral' if optional and not online else 'warn')
            align = self.gateways.aligners.get(p)
            pred = self.pipeline.dashboard_predictions.get(p)
            if pred:
                pred = dict(label=pred[1],confidence=pred[2],age=max(0,now-pred[0]))
            state = self.hub.engine.players[p]
            players.append(dict(id=p,optional=optional,phone=phone,phone_detail=detail,
                gateway=self.badge('Connected','good') if online else self.badge('Disconnected','neutral' if optional else 'bad'),
                gateway_detail='TLS handshake complete on port 8888' if online else 'No active fw4 TLS gateway session',
                hands=hands,pairing=pairing,pair_age=pair_age,
                pairs=align.pairs if align else 0,align_resets=align.resets if align else 0,
                discarded=align.drops if align else 0,prediction=pred,
                hp=round(state.health,2),stamina=round(state.stamina,2)))
        return dict(timestamp=time.time(),uptime=max(0,now-self.started),game=self.hub.engine.phase,
            god_mode=self.hub.engine.god_mode,
            mode=self.args.mode,ai_dir=str(self.args.ai_dir),model=self.pipeline.dashboard_model,
            norm_path=self.pipeline.dashboard_norm,counts=c,players=players,
            pair_rate=max(0,(c['pairs']-pairs)/dt),inference_rate=max(0,(c['inferences']-inferences)/dt),
            worker_alive=self.pipeline.thread.is_alive(),worker_error=self.pipeline.error,
            required_phones=self.args.wait_players,joined_phones=len(self.hub.ready),
            phone_sockets=self.phone_sockets,events=list(self.events))

    async def phone_handle(self, ws):
        self.phone_sockets += 1
        self.event('Phone WSS connected; waiting for ClientHello')
        try:
            await self.hub.handle(ws)
        finally:
            self.phone_sockets -= 1
            self.event('Phone WSS disconnected')

    async def handle(self, reader, writer):
        try:
            async with self._clients:
                raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
                if len(raw)>8192:raise ValueError('request too large')
                method,path,_ = raw.split(b'\r\n',1)[0].decode('ascii').split()
                path = path.partition('?')[0]
                if method != 'GET':
                    status,mime,body='405 Method Not Allowed','text/plain',b'GET only'
                elif path == '/':
                    status,mime,body='200 OK','text/html; charset=utf-8',DASHBOARD_HTML.encode()
                elif path == '/api/status':
                    status,mime,body='200 OK','application/json',json.dumps(self.snapshot(),allow_nan=False).encode()
                else:
                    status,mime,body='404 Not Found','text/plain',b'Not found'
                header=(f'HTTP/1.1 {status}\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\n'
                    'Cache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n'
                    "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'\r\n\r\n")
                writer.write(header.encode()+body)
                await asyncio.wait_for(writer.drain(),3)
        except (asyncio.TimeoutError,asyncio.IncompleteReadError,asyncio.LimitOverrunError,
                ConnectionError,ValueError,UnicodeError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(),1)


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
    monitor = Dashboard(pipeline, gateways, hub, args)
    gateways.monitor = monitor
    dashboard_server = None
    tick = None
    try:
        if not args.no_dashboard:
            dashboard_server = await asyncio.start_server(
                monitor.handle, args.dashboard_host, args.dashboard_port, limit=8192)
            print(f'[DASHBOARD] http://{args.dashboard_host}:{args.dashboard_port} (forward this port through SSH)', flush=True)
        async with await asyncio.start_server(gateways.handle, args.host, 8888, ssl=tls) as esp:
            async with websockets.serve(monitor.phone_handle, args.host, 8889, ssl=phone_tls,
                                        max_size=MAX_MESSAGE_BYTES, close_timeout=2,
                                        ping_interval=PING_INTERVAL_SECONDS,
                                        ping_timeout=PING_INTERVAL_SECONDS):
                tick = asyncio.create_task(periodic_states(hub))
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
        if dashboard_server is not None:
            dashboard_server.close()
            await dashboard_server.wait_closed()
        pipeline.stop.set()
        if tick:
            tick.cancel()
            await asyncio.gather(tick, return_exceptions=True)
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
    parser.add_argument('--ai-dir', type=Path, default=Path('/home/xilinx/ai/integration-check'))
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
    parser.add_argument('--demo-intensity', type=float, default=.6)
    parser.add_argument('--show-samples', action='store_true')
    parser.add_argument('--dashboard-host', default='127.0.0.1')
    parser.add_argument('--dashboard-port', type=int, default=8890)
    parser.add_argument('--no-dashboard', action='store_true')
    args = parser.parse_args()
    if bool(args.phone_cert) != bool(args.phone_key):
        parser.error('--phone-cert and --phone-key go together')
    args.ai_dir = args.ai_dir.expanduser().resolve()
    if not (args.ai_dir / 'src').is_dir():
        parser.error(f'AI source directory not found: {args.ai_dir / "src"}')
    if not 1 <= args.dashboard_port <= 65535 or args.dashboard_port in (8888,8889):
        parser.error('dashboard port must be 1..65535 and different from 8888/8889')
    if args.round_seconds <= 0 or not 0 <= args.demo_intensity <= 1:
        parser.error('invalid round duration/intensity')
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
