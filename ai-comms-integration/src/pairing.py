from collections import deque

from config import LEFT_NODE, MS_PER_S, PAIR_BUFFER_SAMPLES, PAIR_TOLERANCE_MS, RIGHT_NODE


class Pairer:
    def __init__(self, tolerance_ms=PAIR_TOLERANCE_MS, depth=PAIR_BUFFER_SAMPLES):
        self.tolerance_ms = tolerance_ms
        self.pending = {LEFT_NODE: deque(maxlen=depth), RIGHT_NODE: deque(maxlen=depth)}

    def push(self, fields):
        node = fields["node"]
        if node not in self.pending:
            return None

        other = self.pending[RIGHT_NODE if node == LEFT_NODE else LEFT_NODE]
        match = self._nearest(other, fields["timestamp"])
        if match is None:
            self.pending[node].append(fields)
            return None

        for _ in range(match + 1):
            partner = other.popleft()
        self.pending[node].clear()

        left, right = (fields, partner) if node == LEFT_NODE else (partner, fields)
        sample = left["accel"] + left["gyro"] + right["accel"] + right["gyro"]
        t = max(left["timestamp"], right["timestamp"]) / MS_PER_S
        return sample, t

    def _nearest(self, candidates, timestamp):
        best, best_gap = None, None
        for i, candidate in enumerate(candidates):
            gap = abs(candidate["timestamp"] - timestamp)
            if gap <= self.tolerance_ms and (best_gap is None or gap < best_gap):
                best, best_gap = i, gap
        return best
