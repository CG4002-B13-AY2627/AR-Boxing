"""
TLS-encrypted version of real_frame_server.py — wraps the exact same
frame-parsing logic (fragmentation handling, checksum validation) with
an SSL/TLS layer, per Section 4.4's design (preshared self-signed
certificate, since all devices are provisioned ahead of the match — not
CA-signed certs).

Requires server.crt and server.key in the same directory (generated once
with openssl, see setup notes).

Usage:
    python3 real_frame_server_tls.py
"""
import socket
import ssl
import threading
import struct
import time

HOST = '0.0.0.0'
PORT = 8888
CERT_FILE = 'server.crt'
KEY_FILE = 'server.key'

FRAME_LEN = 22


def try_extract_frame(buffer: bytearray):
    # Search again in the SAME buffer after bad framing; do not wait for another
    # recv if a complete valid frame is already buffered behind the bad bytes.
    while buffer:
        if buffer[0] != 0xAA:
            del buffer[0]
            continue
        if len(buffer) < 2:
            return None, buffer
        if buffer[1] != 0x02:
            del buffer[0]
            continue
        if len(buffer) < FRAME_LEN:
            return None, buffer
        candidate = bytes(buffer[:FRAME_LEN])
        if candidate[-1] != 0x55:
            del buffer[0]
            continue
        del buffer[:FRAME_LEN]
        return candidate, buffer
    return None, buffer


def parse_sensor_data(frame: bytes):
    body = frame[1:20]
    received_checksum = frame[20]
    computed_checksum = 0
    for b in body:
        computed_checksum ^= b
    packet_type, player_id, node_id, timestamp, ax, ay, az, gx, gy, gz = \
        struct.unpack('<BBBI3h3h', body)
    return {
        'packet_type': packet_type, 'player_id': player_id, 'node_id': node_id,
        'timestamp': timestamp, 'accel': (ax, ay, az), 'gyro': (gx, gy, gz),
        'checksum_ok': (computed_checksum == received_checksum),
    }


def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected (TLS: {conn.version()})")
    buffer = bytearray()

    with conn:
        while True:
            try:
                chunk = conn.recv(1024)
            except (ConnectionResetError, ssl.SSLError) as e:
                print(f"[DISCONNECTED] {addr} — {e}")
                break

            if not chunk:
                print(f"[DISCONNECTED] {addr} disconnected.")
                break

            buffer.extend(chunk)

            while True:
                frame, buffer = try_extract_frame(buffer)
                if frame is None:
                    break

                result = parse_sensor_data(frame)
                status = "OK" if result['checksum_ok'] else "CHECKSUM FAIL"
                print(f"[{addr}] player={result['player_id']} "
                      f"node={result['node_id']} accel={result['accel']} "
                      f"gyro={result['gyro']} [{status}]")

                if not result['checksum_ok']:
                    continue  # Never acknowledge corrupt sensor data as success.
                conn.sendall(bytes([0xAA, 0x01, result['player_id'], 0x00, 0x55]))

    print(f"[-] {addr} fully closed")


def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

    raw_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw_server.bind((HOST, PORT))
    raw_server.listen()

    print(f"TLS server ready on port {PORT}")

    while True:
        raw_conn, addr = raw_server.accept()
        try:
            tls_conn = context.wrap_socket(raw_conn, server_side=True)
        except ssl.SSLError as e:
            print(f"[TLS HANDSHAKE FAILED] {addr} — {e}")
            raw_conn.close()
            continue
        thread = threading.Thread(target=handle_client, args=(tls_conn, addr), daemon=True)
        thread.start()


if __name__ == "__main__":
    main()
