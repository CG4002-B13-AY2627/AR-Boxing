"""File-demo extension of [AA][type][payload][XOR][55]; integers are LE.

Fixed payload sizes allow arbitrary binary data (including AA/55) and TCP
fragmentation/coalescing without relying on recv() boundaries. DATA includes
CRC32 for its valid bytes; BEGIN carries the full file's SHA-256.
This is a separate demo protocol, not a replacement for the sensor protocol.
"""
import struct
import zlib

START, END = 0xAA, 0x55
BEGIN, DATA, FINISH, ACK = 0x20, 0x21, 0x22, 0x23
OK, COMPLETE, ERROR = 0, 1, 2
CHUNK_SIZE = 256
BEGIN_STRUCT = struct.Struct('<II32s32s')  # transfer id, size, SHA256, ASCII name
DATA_STRUCT = struct.Struct('<IIH256sI')   # id, offset, valid length, bytes, CRC32
ACK_STRUCT = struct.Struct('<IIB')        # id, next expected offset, status
SIZES = {BEGIN: BEGIN_STRUCT.size, DATA: DATA_STRUCT.size, FINISH: 4, ACK: ACK_STRUCT.size}


class ProtocolError(ValueError):
    pass


def checksum(body):
    value = 0
    for byte in body:
        value ^= byte
    return value


def frame(kind, payload):
    if kind not in SIZES or len(payload) != SIZES[kind]:
        raise ProtocolError('invalid packet type or payload size')
    body = bytes([kind]) + payload
    return bytes([START]) + body + bytes([checksum(body), END])


def recv_exact(conn, length):
    """A short recv is normal: continue until length bytes or EOF/timeout."""
    result = bytearray()
    while len(result) < length:
        chunk = conn.recv(length - len(result))
        if not chunk:
            raise EOFError('peer disconnected before packet completed')
        result.extend(chunk)
    return bytes(result)


def recv_frame(conn):
    header = recv_exact(conn, 2)
    if header[0] != START or header[1] not in SIZES:
        raise ProtocolError('invalid frame header')
    kind = header[1]
    tail = recv_exact(conn, SIZES[kind] + 2)
    payload = tail[:-2]
    if tail[-1] != END or tail[-2] != checksum(bytes([kind]) + payload):
        raise ProtocolError('invalid frame footer/checksum')
    return kind, payload


def send_ack(conn, transfer_id, offset, status=OK):
    conn.sendall(frame(ACK, ACK_STRUCT.pack(transfer_id, offset, status)))


def data_packet(transfer_id, offset, data):
    if not 1 <= len(data) <= CHUNK_SIZE:
        raise ProtocolError('invalid data length')
    return frame(DATA, DATA_STRUCT.pack(transfer_id, offset, len(data), data,
                                       zlib.crc32(data) & 0xFFFFFFFF))
