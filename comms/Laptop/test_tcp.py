"""Run beside your UPDATED protocol.py: python test_tcp.py.

Tests the actual parser with controlled recv-like byte chunks. No connection,
server, firmware change or third-party package is needed. This validates code
handling of stream boundaries, not an end-to-end network fault injection.
"""
from pathlib import Path
import importlib.util
import sys

import protocol as P


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run():
    command = P.actuate(0, 2, 113)
    expected = (P.ACTUATE, command[2:-2])

    parser = P.PacketParser()
    require(parser.feed(command[:2]) == [], 'partial header produced a packet')
    require(parser.feed(command[2:3]) == [], 'partial payload produced a packet')
    require(parser.feed(command[3:]) == [expected], 'split command reconstructed incorrectly')
    print('[PASS] 1. Split command: 7 bytes delivered as 2 + 1 + 4')

    commands = [P.actuate(0, 2, value) for value in (17, 113, 238)]
    decoded = P.PacketParser().feed(b''.join(commands))
    require([P.decode(kind, payload)['duration'] for kind, payload in decoded] == [17, 113, 238],
            'coalesced commands lost or changed')
    print('[PASS] 2. Coalesced commands: one chunk contains three complete frames')

    bad = bytearray(command)
    bad[-2] ^= 1  # flip the outer checksum; payload remains the same.
    parser = P.PacketParser()
    require(parser.feed(bytes(bad) + command) == [expected], 'corrupt frame accepted or recovery failed')
    require(parser.bad_checksum == 1, 'corrupt checksum was not counted')
    print('[PASS] 3. Wrong checksum: corrupt frame dropped, next valid frame accepted')

    parser = P.PacketParser()
    # Unknown packet type, arbitrary bytes, then a genuine packet.
    require(parser.feed(b'junk\xaa\xfe\x00' + command) == [expected], 'resynchronization failed')
    print('[PASS] 4. Invalid header: parser finds the next valid frame')

    # Include AA/55 in binary readings: payload bytes must not be mistaken for delimiters.
    sensor = P.sensor_data(1, 1, 123, (170, 85, 8000), (10, -5, 2))
    parser = P.PacketParser()
    for byte in sensor[:-1]:
        require(parser.feed(bytes([byte])) == [], 'partial sensor frame accepted')
    result = parser.feed(sensor[-1:])
    require(len(result) == 1, 'sensor frame did not complete')
    fields = P.decode(*result[0])
    require(fields['accel'] == (170, 85, 8000) and fields['gyro'] == (10, -5, 2),
            'sensor data changed during reconstruction')
    print('[PASS] 5. Sensor frame: 22 one-byte chunks reconstructed without changing readings')

    # The laptop folder contains this client. Import it only if present; importing
    # does NOT execute its main() or open a network connection.
    client_path = Path(__file__).with_name('real_frame_client_tls.py')
    if client_path.exists():
        spec = importlib.util.spec_from_file_location('tcp_test_client', client_path)
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        if not hasattr(client, 'read_ack'):
            raise AssertionError('client is an old version: read_ack() is missing')
        class Reply:
            def __init__(self, data):
                self.data = data
            def recv(self, length):
                part, self.data = self.data[:1], self.data[1:]
                return part
        ack = bytes([0xAA, 1, 1, 0, 0x55])
        require(client.read_ack(Reply(ack), 1) == ack, 'fragmented ACK reconstruction failed')
        print('[PASS] 6. ACK: five one-byte chunks read and validated')
        try:
            client.read_ack(Reply(ack[:2]), 1)
        except ConnectionError:
            pass
        else:
            raise AssertionError('truncated ACK incorrectly reported success')
        print('[PASS] 7. Truncated ACK: connection failure reported instead of success')
    print('\nAll checks passed. No network connections or files were modified.')
    print('These are controlled byte-stream tests, not live network fault injection.')


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(f'[FAIL] {error}', file=sys.stderr)
        sys.exit(1)
