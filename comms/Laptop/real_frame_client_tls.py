"""Laptop TLS sensor-frame demo; pair ONLY with real_frame_server_tls.py.
Edit DUMMY_SAMPLES below, save and rerun when asked to change the dummy data.
Frames retain the actual 22-byte IMU format. No ESP reflash is needed here.
"""
import argparse
import random
import socket
import ssl
import struct
import time

HOST = 'localhost'
PORT = 8888
CERT_FILE = 'server.crt'

# LIVE EDIT HERE: (accel XYZ, gyro XYZ); six signed int16 readings.
# Keep values in -32768..32767. Change readings, not the packet layout.
DUMMY_SAMPLES = [
    ((1200, -300, 8000), (50, -20, 5)),
    ((1500, -200, 9000), (20, -10, 3)),
    ((-600, 900, 7600), (-30, 15, -8)),
    ((400, -1200, 8300), (12, 25, -6)),
]


def build_frame(player_id, node_id, timestamp, accel_xyz, gyro_xyz):
    body = struct.pack('<BBBI3h3h', 0x02, player_id, node_id, timestamp,
                       *accel_xyz, *gyro_xyz)
    checksum = 0
    for b in body:
        checksum ^= b
    return bytes([0xAA]) + body + bytes([checksum, 0x55])


def recv_exact(conn, length):
    """TCP may split an ACK: read all bytes or report EOF/timeout."""
    result = bytearray()
    while len(result) < length:
        data = conn.recv(length - len(result))
        if not data:
            raise ConnectionError('server closed before a complete ACK arrived')
        result.extend(data)
    return bytes(result)


def read_ack(conn, player_id):
    # Standalone legacy ACK: 5 bytes. NOT protocol.py's 9-byte HANDSHAKE_ACK.
    ack = recv_exact(conn, 5)
    if ack != bytes([0xAA, 0x01, player_id, 0x00, 0x55]):
        raise ValueError('invalid standalone ACK')
    return ack


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--count', type=int, default=5)
    ap.add_argument('--interval', type=float, default=0.6)
    args = ap.parse_args()
    if args.count < 1 or args.interval < 0 or not DUMMY_SAMPLES:
        ap.error('count must be >=1, interval >=0, and DUMMY_SAMPLES nonempty')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(CERT_FILE)
    context.check_hostname = False  # Same policy as the recorded standalone test.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw_sock:
        raw_sock.settimeout(8)
        with context.wrap_socket(raw_sock, server_hostname=HOST) as tls_sock:
            tls_sock.connect((HOST, PORT))
            print(f'Connected via TLS ({tls_sock.version()})')
            player, node = 1, 0x01
            pool = []
            for index in range(1, args.count + 1):
                # Random order without replacement: each cycle shows all samples.
                if not pool:
                    pool = list(DUMMY_SAMPLES)
                    random.shuffle(pool)
                accel, gyro = pool.pop()
                timestamp = int(time.time() * 1000) & 0xFFFFFFFF
                tls_sock.sendall(build_frame(player, node, timestamp, accel, gyro))
                print(f'[TX {index}] SENSOR_DATA player={player} node={node} '
                      f'timestamp={timestamp} accel={accel} gyro={gyro}')
                read_ack(tls_sock, player)
                print(f'[RX {index}] ACK player={player} valid')
                if index < args.count:
                    time.sleep(args.interval)


if __name__ == '__main__':
    main()
