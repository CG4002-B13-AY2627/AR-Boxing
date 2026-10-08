#!/usr/bin/env python3
"""Receive a TLS-encrypted file from an ESP32, check it, and publish it.

Each connection owns its temporary file. No output is committed until the
declared size AND SHA-256 match. Interrupted/invalid uploads are deleted.
Reconnects start a NEW transfer at byte zero; this demo does not resume.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import socket
import ssl
import struct
import tempfile
import threading
import time
import uuid
import zlib

import file_protocol as P

PRINT_LOCK = threading.Lock()
MAX_SIZE = 1024 * 1024  # 1 MiB demo limit; bounds an incomplete upload.


def say(message):
    with PRINT_LOCK:
        print(message, flush=True)


def receive_upload(conn, output_dir, label='ESP32'):
    """Public entry point also used by the integration tests with real sockets."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    transfer_id = 0
    received = 0
    try:
        kind, payload = P.recv_frame(conn)
        if kind != P.BEGIN:
            raise P.ProtocolError('BEGIN must be the first packet')
        transfer_id, size, expected_hash, raw_name = P.BEGIN_STRUCT.unpack(payload)
        name = raw_name.split(b'\0', 1)[0].decode('ascii', errors='strict')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', name):
            raise P.ProtocolError('invalid filename')
        if size > MAX_SIZE:
            raise P.ProtocolError('file exceeds 1 MiB limit')
        digest = hashlib.sha256()
        started = time.monotonic()
        last_report = started
        fd, temp_path = tempfile.mkstemp(prefix='.upload-', suffix='.part', dir=output_dir)
        say(f'[{label}] BEGIN id={transfer_id} file={name} size={size} bytes')
        say(f'[{label}] EXPECTED SHA256 {expected_hash.hex()}')
        with os.fdopen(fd, 'wb') as output:
            P.send_ack(conn, transfer_id, 0)
            while True:
                kind, payload = P.recv_frame(conn)
                if kind == P.DATA:
                    tid, offset, length, padded, crc = P.DATA_STRUCT.unpack(payload)
                    if tid != transfer_id or offset != received:
                        raise P.ProtocolError('wrong transfer id or out-of-order offset')
                    if not 1 <= length <= P.CHUNK_SIZE or received + length > size:
                        raise P.ProtocolError('invalid chunk length')
                    data = padded[:length]
                    if zlib.crc32(data) & 0xFFFFFFFF != crc:
                        raise P.ProtocolError(f'chunk CRC32 mismatch at offset {offset}')
                    output.write(data)
                    digest.update(data)
                    received += length
                    P.send_ack(conn, transfer_id, received)
                    now = time.monotonic()
                    if now - last_report >= 1.0:
                        say(f'[{label}] PROGRESS {received}/{size} bytes | chunk CRC32 OK')
                        last_report = now
                elif kind == P.FINISH:
                    if struct.unpack('<I', payload)[0] != transfer_id:
                        raise P.ProtocolError('wrong FINISH transfer id')
                    if received != size:
                        raise P.ProtocolError(f'incomplete file: {received}/{size} bytes')
                    actual_hash = digest.digest()
                    if actual_hash != expected_hash:
                        raise P.ProtocolError('whole-file SHA256 mismatch')
                    output.flush()
                    os.fsync(output.fileno())
                    break
                else:
                    raise P.ProtocolError('unexpected packet during upload')
        # Unique names avoid concurrent boards/retries overwriting each other.
        final_path = output_dir / f'{transfer_id:08x}_{uuid.uuid4().hex[:8]}_{name}'
        os.replace(temp_path, final_path)
        temp_path = None
        elapsed = max(time.monotonic() - started, 0.000001)
        say(f'[{label}] FILE VERIFIED | {received} bytes | {elapsed:.2f} s | '
            f'{received * 8 / elapsed / 1000:.1f} kbps (file payload)')
        say(f'[{label}] RECEIVED SHA256 {actual_hash.hex()}')
        say(f'[{label}] SAVED {final_path.resolve()}')
        # COMPLETE only after validation and atomic publication. A lost final
        # ACK may produce a second verified copy on retry, never false success.
        P.send_ack(conn, transfer_id, received, P.COMPLETE)
        return final_path
    except (P.ProtocolError, EOFError, OSError, UnicodeError) as error:
        say(f'[{label}] TRANSFER FAILED | {received} bytes | {error}')
        try:
            P.send_ack(conn, transfer_id, received, P.ERROR)
        except OSError:
            pass
        return None
    finally:
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


def handle_client(raw, address, context, output_dir):
    label = f'{address[0]}:{address[1]}'
    try:
        raw.settimeout(10)
        with context.wrap_socket(raw, server_side=True) as conn:
            conn.settimeout(15)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            say(f'[{label}] TLS {conn.version()} | {conn.cipher()[0]}')
            receive_upload(conn, output_dir, label)
    except (OSError, ssl.SSLError) as error:
        say(f'[{label}] CONNECTION FAILED | {error}')
    finally:
        raw.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--cert', default='server.crt')
    parser.add_argument('--key', default='server.key')
    parser.add_argument('--output-dir', default='received_files')
    args = parser.parse_args()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', args.port))
        server.listen()
        say(f'File server ready on port {args.port} (TLS); stop comms_server.py first')
        try:
            while True:
                raw, address = server.accept()
                threading.Thread(target=handle_client,
                                 args=(raw, address, context, args.output_dir),
                                 daemon=True).start()
        except KeyboardInterrupt:
            say('File server stopped. Unfinished uploads are not verified files.')


if __name__ == '__main__':
    main()
