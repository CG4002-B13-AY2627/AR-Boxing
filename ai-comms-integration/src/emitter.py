import queue

from messages import to_message


class Emitter:
    def __init__(self, out_q):
        self.out_q = out_q

    def emit(self, player, events):
        for event in events:
            try:
                self.out_q.put_nowait(to_message(player, event))
            except queue.Full:
                pass
