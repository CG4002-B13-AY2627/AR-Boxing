"""Laptop keyboard -> binary ACTUATE frames -> Ultra96 port 8891.
Requires protocol.py beside this file and the UPDATED comms_server.py remotely.
One key sends one random command; Ctrl+C exits. --enter keeps line-input mode.
Node 0 means broadcast on this command channel ONLY: Ultra96 rewrites it to
an actual node ID before forwarding. Each command is a real 7-byte packet.
"""
import argparse
import contextlib
import random
import socket
import sys

import protocol as P

HOST = 'localhost'
PORT = 8891
# LIVE EDIT HERE: valid trigger values are unsigned bytes (0..255).
DUMMY_VALUES = [17, 41, 113, 150, 238]


@contextlib.contextmanager
def key_reader(enter_mode=False):
    """Windows/Unix per-key input; restore Unix terminal settings on exit."""
    if enter_mode or not sys.stdin.isatty():
        yield lambda: input()
    elif sys.platform == 'win32':
        import msvcrt
        def read_windows_key():
            while True:
                key = msvcrt.getwch()
                if key == '\x03':
                    raise KeyboardInterrupt
                if key in ('\x00', '\xe0'):
                    msvcrt.getwch()  # consume function/arrow key's second code
                    continue
                return key
        yield read_windows_key
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            yield lambda: sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--enter', action='store_true', help='send after input + Enter')
    ap.add_argument('--node', type=int, default=0, help='0=broadcast, 1..255=target')
    args = ap.parse_args()
    if not 0 <= args.node <= 255 or not DUMMY_VALUES or any(
            not isinstance(v, int) or not 0 <= v <= 255 for v in DUMMY_VALUES):
        ap.error('node and DUMMY_VALUES must contain byte values 0..255')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(8)
        client.connect((HOST, PORT))
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f'Connected to Ultra96 command channel at {HOST}:{PORT}')
        print('Press a key to send a random ACTUATE frame (Ctrl+C to quit)' if not args.enter
              else 'Press Enter to send a random ACTUATE frame (Ctrl+C to quit)')
        try:
            with key_reader(args.enter) as read_key:
                while True:
                    read_key()
                    value = random.choice(DUMMY_VALUES)
                    client.sendall(P.actuate(args.node, 0x02, value))
                    print(f'Sent dummy trigger: {value} '
                          f'(ACTUATE node={args.node} command=2 bytes=7)')
        except (KeyboardInterrupt, EOFError):
            print('\nKeyboard sender stopped.')


if __name__ == '__main__':
    main()
