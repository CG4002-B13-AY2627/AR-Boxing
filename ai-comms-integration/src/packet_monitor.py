import time

from config import MONITOR_INTERVAL_S


class PacketMonitor:
    def __init__(self, interval=MONITOR_INTERVAL_S):
        self.interval = interval
        self.packets = {}
        self.packet_ts = {}
        self.samples = {}
        self.sample_t = {}
        self.windows = {}
        self.started = time.time()

    def record_packet(self, fields):
        key = (fields["player"], fields["node"])
        self.packets[key] = self.packets.get(key, 0) + 1
        self.packet_ts[key] = fields["timestamp"]

    def record_sample(self, player, t):
        self.samples[player] = self.samples.get(player, 0) + 1
        self.sample_t[player] = t

    def record_window(self, player):
        self.windows[player] = self.windows.get(player, 0) + 1

    def record_event(self, player, event):
        print(f"[AI] event P{player} {event}", flush=True)

    def report(self):
        now = time.time()
        elapsed = now - self.started
        if elapsed < self.interval:
            return

        if self.packets:
            line = " | ".join(
                f"P{p} N{n} {c / elapsed:.0f}/s ts={self.packet_ts[(p, n)]}"
                for (p, n), c in sorted(self.packets.items())
            )
            print(f"[AI] packets {line}", flush=True)

        if self.samples:
            line = " | ".join(
                f"P{p} {c / elapsed:.0f}/s t={self.sample_t[p]:.3f}"
                for p, c in sorted(self.samples.items())
            )
            print(f"[AI] samples {line}", flush=True)

        if self.windows:
            line = " | ".join(
                f"P{p} {c / elapsed:.0f}/s"
                for p, c in sorted(self.windows.items())
            )
            print(f"[AI] windows {line}", flush=True)

        self.packets.clear()
        self.samples.clear()
        self.windows.clear()
        self.started = now
