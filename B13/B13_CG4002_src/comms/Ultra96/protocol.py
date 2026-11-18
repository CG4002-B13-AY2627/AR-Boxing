"""
Packet definitions for the ESP32 <-> Ultra96 link, following Section 4.2 of the
design report. Shared by comms_server.py (and by any test client).

Every packet has the same envelope:

    [0xAA][Type][ ...payload... ][Checksum][0x55]

Checksum = XOR of every byte from Type through the end of the payload.
All multi-byte integers are little-endian.

  Type  Name           Bytes  Payload
  0x00  HANDSHAKE        7    player id, node id, firmware version
  0x01  HANDSHAKE_ACK    9    session id, server time (uint32 ms since server start)
  0x02  SENSOR_DATA     22    player, node, timestamp (uint32), accel x3, gyro x3 (int16)
  0x03  HEARTBEAT        6    player id, node id
  0x04  HEARTBEAT_ACK    5    session id                       (layout not in the report; defined here)
  0x05  SYNC_SENSOR     26    player, node, right-clock uint32 ms, 6 int16 axes, uint32 sync epoch
  0x10  ACTUATE          7    node id, command (1 start / 0 stop), duration ms (0-255)
  0x1F  DISCONNECT       6    player id, node id               (layout not in the report; defined here)
"""
# Port 8891's keyboard trigger also uses ACTUATE: command=0x02 is the existing
# modify-and-reply demo command, and duration holds its uint8 dummy value.
# On that laptop->Ultra96 channel ONLY, node=0 broadcasts. Ultra96 rewrites it
# to each actual device ID before sending the same packet type to an ESP.
import struct

START = 0xAA
END = 0x55

HANDSHAKE = 0x00
HANDSHAKE_ACK = 0x01
SENSOR_DATA = 0x02
HEARTBEAT = 0x03
HEARTBEAT_ACK = 0x04
SYNC_SENSOR = 0x05  # fw4: common gateway clock + synchronization epoch
ACTUATE = 0x10
DISCONNECT = 0x1F

NAMES = {
    SYNC_SENSOR: "SYNC_SENSOR",
    HANDSHAKE: "HANDSHAKE", HANDSHAKE_ACK: "HANDSHAKE_ACK", SENSOR_DATA: "SENSOR_DATA",
    HEARTBEAT: "HEARTBEAT", HEARTBEAT_ACK: "HEARTBEAT_ACK", ACTUATE: "ACTUATE",
    DISCONNECT: "DISCONNECT",
}

# Total packet length in bytes, start byte and footer included.
LENGTHS = {
    SYNC_SENSOR: 26,
    HANDSHAKE: 7, HANDSHAKE_ACK: 9, SENSOR_DATA: 22, HEARTBEAT: 6,
    HEARTBEAT_ACK: 5, ACTUATE: 7, DISCONNECT: 6,
}


def checksum(data):
    x = 0
    for b in data:
        x ^= b
    return x


def build(ptype, payload=b''):
    body = bytes([ptype]) + payload
    pkt = bytes([START]) + body + bytes([checksum(body), END])
    assert len(pkt) == LENGTHS[ptype], f"{NAMES[ptype]} must be {LENGTHS[ptype]} bytes, got {len(pkt)}"
    return pkt


def handshake(player, node, fw_version):
    return build(HANDSHAKE, bytes([player, node, fw_version]))


def handshake_ack(session, server_time_ms):
    return build(HANDSHAKE_ACK, bytes([session]) + struct.pack('<I', server_time_ms & 0xFFFFFFFF))


def sensor_data(player, node, timestamp, accel, gyro):
    return build(SENSOR_DATA, struct.pack('<BBI3h3h', player, node, timestamp & 0xFFFFFFFF, *accel, *gyro))


def heartbeat(player, node):
    return build(HEARTBEAT, bytes([player, node]))


def heartbeat_ack(session):
    return build(HEARTBEAT_ACK, bytes([session]))


def actuate(node, command, duration_ms):
    return build(ACTUATE, bytes([node, command, duration_ms]))


def disconnect(player, node):
    return build(DISCONNECT, bytes([player, node]))


def decode(ptype, payload):
    """Turns a packet's payload bytes into a dict of named fields."""
    if ptype == HANDSHAKE:
        p, n, fw = payload
        return dict(player=p, node=n, fw=fw)
    if ptype == HANDSHAKE_ACK:
        return dict(session=payload[0], server_time=struct.unpack('<I', payload[1:5])[0])
    if ptype == SYNC_SENSOR:
        p, n, ts, ax, ay, az, gx, gy, gz, epoch = struct.unpack('<BBI6hI', payload)
        return dict(player=p, node=n, timestamp=ts, accel=(ax,ay,az), gyro=(gx,gy,gz), epoch=epoch)
    if ptype == SENSOR_DATA:
        p, n, ts, ax, ay, az, gx, gy, gz = struct.unpack('<BBI3h3h', payload)
        return dict(player=p, node=n, timestamp=ts, accel=(ax, ay, az), gyro=(gx, gy, gz))
    if ptype in (HEARTBEAT, DISCONNECT):
        return dict(player=payload[0], node=payload[1])
    if ptype == HEARTBEAT_ACK:
        return dict(session=payload[0])
    if ptype == ACTUATE:
        return dict(node=payload[0], command=payload[1], duration=payload[2])
    raise ValueError(f"unknown packet type {ptype:#x}")


def describe(ptype, fields):
    """Human-readable one-liner for logs (the assessment asks for readable logs,
    not raw hex)."""
    name = NAMES.get(ptype, f"TYPE_{ptype:#x}")
    return f"{name} " + " ".join(f"{k}={v}" for k, v in fields.items())


class PacketParser:
    """Reassembles packets from a TCP byte stream: a packet may arrive split
    across reads, or glued to the next one. Lengths come from the type byte, so
    payload bytes that happen to equal 0xAA or 0x55 cannot confuse it."""

    def __init__(self):
        self.buf = bytearray()
        self.bad_checksum = 0
        self.resync_bytes = 0     # bytes skipped while looking for a valid packet start

    def feed(self, data):
        """Returns a list of (type, payload_bytes) for every complete, valid packet."""
        buf = self.buf
        buf.extend(data)
        out = []
        while buf:
            if buf[0] != START:
                idx = buf.find(START)
                if idx == -1:
                    self.resync_bytes += len(buf)
                    buf.clear()
                    break
                self.resync_bytes += idx
                del buf[:idx]
            if len(buf) < 2:
                break
            length = LENGTHS.get(buf[1])
            if length is None:                 # not a known type: this 0xAA was not a start
                self.resync_bytes += 1
                del buf[0]
                continue
            if len(buf) < length:
                break                          # wait for the rest
            pkt = bytes(buf[:length])
            if pkt[-1] != END:                 # footer not where it should be
                self.resync_bytes += 1
                del buf[0]
                continue
            if checksum(pkt[1:-2]) != pkt[-2]:
                self.bad_checksum += 1         # framing looks right but content is corrupt
                del buf[:length]
                continue
            del buf[:length]
            out.append((pkt[1], pkt[2:-2]))
        return out
