"""
Ultra96 server for the ESP32 link, implementing the packet protocol from
Section 4.2 of the design report (see protocol.py for the byte layouts).

Per connection it handles:
  HANDSHAKE      -> registers the node, assigns a session id, replies with
                    HANDSHAKE_ACK carrying the server time (for clock alignment,
                    Section 4.7)
  SENSOR_DATA    -> validated and counted; ignored until the handshake is done
  HEARTBEAT      -> replied to with HEARTBEAT_ACK
  DISCONNECT     -> graceful close
  (silence)      -> a peer that sends nothing for --timeout seconds is dropped
And it can send ACTUATE (type 0x10) to a node, from the console (see below).

Output is deliberately not cluttered: one line per second per connection, each
connection in its own colour. Use --verbose for one line per packet, and --log
FILE for a human-readable record of every packet (not raw hex).

Console commands while it runs (type the whole line, then Enter; use --quiet so output doesn't scroll under your typing):
    a <node> [ms]   send ACTUATE (start, duration ms, default 200) to that node id
    list            show connected sessions

Usage:
    python3 comms_server.py [--port 8888] [--tls] [--verbose] [--quiet] [--log FILE] [--timeout 3.5]
Needs protocol.py next to it. With --tls it also needs server.crt and server.key
(or the files named by --cert / --key).
"""
import argparse
import os
import socket
import ssl
import sys
import threading
import time

import protocol as P

COLOURS = ['\033[36m', '\033[33m', '\033[35m', '\033[32m', '\033[34m', '\033[91m']
RESET = '\033[0m'

START_TIME = time.time()
print_lock = threading.Lock()
log_lock = threading.Lock()
sessions_lock = threading.Lock()
sessions = {}                 # session id -> Session
_next_session = [0]
_next_conn_index = [0]
args = None
logfile = None
tls_ctx = None

def server_time_ms():
    """Milliseconds since this server started: the clock the ESP32s align to."""
    return int((time.time() - START_TIME) * 1000) & 0xFFFFFFFF


def alloc_session_id():
    with sessions_lock:
        _next_session[0] = _next_session[0] % 255 + 1      # 1..255, never 0
        return _next_session[0]


class Session:
    def __init__(self, conn, addr, colour):
        self.conn = conn
        self.addr = addr
        self.colour = colour
        self.sid = None
        self.player = None
        self.node = None
        self.fw = None
        self.send_lock = threading.Lock()
        self.stopping = False      # True when the server is shutting down (Ctrl+C)

    @property
    def tag(self):
        if self.sid is None:
            return f"[{self.addr[0]}:{self.addr[1]}]"
        return f"[S{self.sid} P{self.player} N{self.node}]"

    def send(self, pkt):
        with self.send_lock:
            self.conn.sendall(pkt)


def say(sess, text):
    with print_lock:
        print(f"{sess.colour}{sess.tag} {text}{RESET}", flush=True)


def record(sess, direction, ptype, fields, note=""):
    """Human-readable packet log (only if --log was given)."""
    if logfile is None:
        return
    line = (f"{time.strftime('%H:%M:%S')}.{int((time.time() % 1) * 1000):03d} "
            f"{sess.tag} {direction} {P.describe(ptype, fields)} {note}".rstrip())
    with log_lock:
        logfile.write(line + "\n")
        logfile.flush()


def handle_client(raw_conn, addr, index):
    sess = Session(raw_conn, addr, COLOURS[index % len(COLOURS)])
    parser = P.PacketParser()
    conn = raw_conn

    if args.tls:
        t0 = time.time()
        try:
            raw_conn.settimeout(10)            # a client that never finishes the handshake must not hang a thread
            conn = tls_ctx.wrap_socket(raw_conn, server_side=True)
            sess.conn = conn
        except (ssl.SSLError, OSError) as e:
            say(sess, f"TLS handshake failed: {e}")
            raw_conn.close()
            return
        say(sess, f"connected over {conn.version()}, {conn.cipher()[0]} "
                  f"(TLS handshake took {(time.time() - t0) * 1000:.0f} ms)")
    else:
        say(sess, "connected")

    conn.settimeout(args.timeout)
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass

    frames = heartbeats = dropped_early = 0
    win_frames = 0
    win_start = time.time()
    last_accel = last_gyro = None
    last_frame_t = 0.0
    graceful = False
    reason = "connection closed"

    try:
        while not graceful:
            try:
                data = conn.recv(65536)
            except socket.timeout:
                reason = f"no packets for {args.timeout:g} s, dropping"
                break
            except (OSError, ssl.SSLError) as e:
                if 'timed out' in str(e).lower():
                    reason = f"no packets for {args.timeout:g} s, dropping"
                break
            if not data:
                break

            for ptype, payload in parser.feed(data):
                fields = P.decode(ptype, payload)

                if ptype == P.HANDSHAKE:
                    if sess.sid is None:
                        sess.sid = alloc_session_id()
                        with sessions_lock:
                            sessions[sess.sid] = sess
                    sess.player, sess.node, sess.fw = fields['player'], fields['node'], fields['fw']
                    record(sess, "<-", ptype, fields)
                    ack = P.handshake_ack(sess.sid, server_time_ms())
                    sess.send(ack)
                    record(sess, "->", P.HANDSHAKE_ACK, dict(session=sess.sid, server_time=server_time_ms()))
                    say(sess, f"HANDSHAKE ok: player {sess.player}, node {sess.node}, "
                              f"firmware v{sess.fw} -> session {sess.sid} "
                              f"(server up for {server_time_ms() / 1000:.1f} s)")
                    continue

                if sess.sid is None:
                    dropped_early += 1
                    if dropped_early == 1:
                        say(sess, f"{P.NAMES[ptype]} received before HANDSHAKE, ignored")
                    record(sess, "<-", ptype, fields, "(dropped: no handshake yet)")
                    continue

                if ptype == P.SENSOR_DATA:
                    frames += 1
                    win_frames += 1
                    last_frame_t = time.time()
                    last_accel, last_gyro = fields['accel'], fields['gyro']
                    record(sess, "<-", ptype, fields, "checksum=OK")
                    if args.verbose:
                        say(sess, f"SENSOR_DATA ts={fields['timestamp']} accel={fields['accel']} gyro={fields['gyro']}")
                elif ptype == P.HEARTBEAT:
                    heartbeats += 1
                    record(sess, "<-", ptype, fields)
                    sess.send(P.heartbeat_ack(sess.sid))
                    if args.verbose or time.time() - last_frame_t > 0.5:      # idle: nothing else would show life
                        say(sess, f"HEARTBEAT -> HEARTBEAT_ACK (idle, {heartbeats} so far)")
                elif ptype == P.DISCONNECT:
                    record(sess, "<-", ptype, fields)
                    graceful = True
                    reason = "peer sent DISCONNECT (graceful)"
                    break
                else:
                    record(sess, "<-", ptype, fields, "(unexpected direction)")

            now = time.time()
            if win_frames and now - win_start >= 1.0:
                dt = now - win_start
                if not args.quiet:
                    say(sess, f"{win_frames / dt:5.0f} fps | {win_frames * 22 * 8 / 1000 / dt:6.1f} kbps | "
                              f"last accel={last_accel} gyro={last_gyro} | heartbeats={heartbeats} "
                              f"| bad checksum={parser.bad_checksum}")
                win_frames = 0
                win_start = now
            elif not win_frames and now - win_start >= 1.0:
                win_start = now
    finally:
        if sess.stopping:
            reason = "server shutting down (DISCONNECT sent)"
        say(sess, f"{reason} | {frames} frames, {heartbeats} heartbeats, "
                  f"{parser.bad_checksum} bad checksum, {dropped_early} dropped before handshake")
        if sess.sid is not None:
            with sessions_lock:
                sessions.pop(sess.sid, None)
        try:
            conn.close()
        except OSError:
            pass


def handle_console_line(line):
    parts = line.split()
    if not parts:
        return
    if parts[0] == 'list':
        with sessions_lock:
            items = list(sessions.values())
        with print_lock:
            print("sessions:", ", ".join(f"S{s.sid}(P{s.player} N{s.node})" for s in items) or "none", flush=True)
    elif parts[0] == 'a' and len(parts) >= 2:
        try:
            node = int(parts[1], 0)
            duration = int(parts[2]) if len(parts) > 2 else 200
            if not 0 <= duration <= 255:
                raise ValueError
        except ValueError:
            print("usage: a <node id> [duration 0-255 ms]", flush=True)
            return
        with sessions_lock:
            targets = [s for s in sessions.values() if s.node == node]
        if not targets:
            print(f"no connected session for node {node}", flush=True)
        for s in targets:
            try:
                s.send(P.actuate(node, 0x01, duration))
                record(s, "->", P.ACTUATE, dict(node=node, command=1, duration=duration))
                say(s, f"ACTUATE sent: start, {duration} ms")
            except OSError:
                say(s, "ACTUATE failed: connection is dead")
    else:
        print("commands: 'a <node> [ms]', 'list'", flush=True)


def console():
    """Lets you type commands while the server runs. Reads raw bytes so that a bad
    character (for example full-width letters from a Chinese input method) can never
    kill this thread, and guards every command so nothing typed can either."""
    if sys.stdin is None:
        return
    stream = getattr(sys.stdin, 'buffer', None)
    while True:
        try:
            raw = stream.readline() if stream else sys.stdin.readline().encode('utf-8', 'replace')
        except (OSError, ValueError):
            return
        if not raw:
            return                          # stdin closed
        try:
            line = raw.decode('ascii')
        except UnicodeDecodeError:
            with print_lock:
                print("console: ignored input containing non-English characters. If you use a Chinese "
                      "input method, switch to English / half-width mode and retype.", flush=True)
            continue
        try:
            handle_console_line(line)
        except Exception as e:              # never let the console thread die
            with print_lock:
                print(f"console: error handling {line.strip()!r}: {e}", flush=True)


def shutdown_all():
    """Ctrl+C: tell every ESP32 we're leaving (DISCONNECT), close, and let each
    connection print its summary before the process exits."""
    with sessions_lock:
        items = list(sessions.values())
    with print_lock:
        print(f"\nshutting down, closing {len(items)} connection(s)...", flush=True)
    for s in items:
        s.stopping = True
        try:
            s.send(P.disconnect(s.player, s.node))
        except OSError:
            pass
        try:
            s.conn.shutdown(socket.SHUT_RDWR)
        except (OSError, ssl.SSLError):
            pass
    time.sleep(0.6)               # give each connection thread time to print its summary


def main():
    global args, logfile
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8888)
    ap.add_argument('--tls', action='store_true', help='wrap connections in TLS (needs server.crt / server.key)')
    ap.add_argument('--cert', default='server.crt', help='certificate file for --tls (default server.crt)')
    ap.add_argument('--key', default='server.key', help='private key file for --tls (default server.key)')
    ap.add_argument('--verbose', action='store_true', help='print every packet')
    ap.add_argument('--quiet', action='store_true', help='no per-second rate lines (easier to type commands)')
    ap.add_argument('--log', metavar='FILE', help='write a human-readable log of every packet')
    ap.add_argument('--timeout', type=float, default=3.5,
                    help='drop a peer silent for this many seconds (3 missed heartbeats + slack)')
    args = ap.parse_args()
    if args.log:
        logfile = open(args.log, 'a')
    if args.tls:
        global tls_ctx
        try:
            tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls_ctx.load_cert_chain(args.cert, args.key)
        except (FileNotFoundError, ssl.SSLError) as e:
            sys.exit(f"cannot start with --tls: {e}\n"
                     f"{args.cert} and {args.key} must exist (see make_cert.py)")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', args.port))
    server.listen()
    print(f"comms server ready on port {args.port} "
          f"({'TLS' if args.tls else 'plain TCP'}, peer timeout {args.timeout:g} s)", flush=True)

    threading.Thread(target=console, daemon=True).start()

    try:
        while True:
            conn, addr = server.accept()
            idx = _next_conn_index[0]
            _next_conn_index[0] += 1
            threading.Thread(target=handle_client, args=(conn, addr, idx), daemon=True).start()
    except KeyboardInterrupt:
        shutdown_all()
        if logfile:
            logfile.close()
        sys.stdout.flush()
        # Leave immediately instead of letting Python finalise. The console thread is
        # blocked reading stdin and holds its lock; on a real terminal, finalisation
        # then aborts with "Fatal Python error: _enter_buffered_busy ... core dumped".
        # Everything has been flushed and every connection closed by this point.
        os._exit(0)
    finally:
        if logfile:
            logfile.close()


if __name__ == "__main__":
    main()
