"""Bounded interpolation on the gateway's common millisecond clock.

No clock offset is inferred from TCP arrival times. Firmware-v4 type 0x05
already carries right-clock timestamps plus a synchronization epoch.
"""
from bisect import bisect_left
import math

CHANNELS = [side + '_' + axis for side in ('l', 'r')
            for axis in ('ax', 'ay', 'az', 'gx', 'gy', 'gz')]


class Aligner:
    def __init__(self):
        self.epoch = None
        self.reference = None
        self.nodes = {1: [], 2: []}
        self.target = None
        self.segment = 0
        self.pairs = 0
        self.resets = 0
        self.drops = 0
        self.interpolated_axes_groups = 0

    def reset(self):
        self.nodes = {1: [], 2: []}
        self.target = None
        self.segment += 1
        self.resets += 1

    @staticmethod
    def at(rows, target):
        times = [row[0] for row in rows]
        i = bisect_left(times, target)
        if i < len(rows) and rows[i][0] == target:
            return rows[i][1]
        if i == 0 or i == len(rows):
            return None
        ta, a = rows[i-1]
        tb, b = rows[i]
        if tb - ta > 25:
            return None
        weight = (target-ta)/(tb-ta)
        return [x + (y-x)*weight for x, y in zip(a, b)]

    def push(self, node, timestamp, epoch, values):
        if node not in (1, 2) or len(values) != 6:
            raise ValueError('expected one six-axis sample from node 1 or 2')
        if self.epoch is not None and epoch < self.epoch:
            self.drops += 1
            return []
        if epoch != self.epoch:
            self.epoch = epoch
            self.reset()
        if self.reference is None:
            stamp = timestamp
        else:
            stamp = self.reference + ((timestamp - self.reference + 2**31) % 2**32 - 2**31)
        self.reference = max(stamp, self.reference or stamp)
        rows = self.nodes[node]
        if rows and stamp <= rows[-1][0]:
            self.drops += 1
            return []
        if rows and stamp - rows[-1][0] > 25:
            self.reset()
        other = self.nodes[3-node]
        if other and stamp - other[-1][0] > 100:
            self.reset()
        self.nodes[node].append((stamp, list(values)))
        self.nodes[node] = self.nodes[node][-32:]
        if not all(self.nodes.values()):
            return []
        start = max(self.nodes[n][0][0] for n in (1, 2))
        if self.target is None or self.target < start:
            self.target = math.ceil(start / 10) * 10
        end = min(self.nodes[n][-1][0] for n in (1, 2))
        out = []
        while self.target <= end:
            left = self.at(self.nodes[1], self.target)
            right = self.at(self.nodes[2], self.target)
            if left is None or right is None:
                # Never bridge a missing span with a fabricated constant sample.
                self.reset()
                break
            self.interpolated_axes_groups += sum(
                not any(row[0] == self.target for row in self.nodes[n]) for n in (1, 2))
            out.append((self.segment, self.target / 1000, left + right))
            self.pairs += 1
            self.target += 10
        return out
