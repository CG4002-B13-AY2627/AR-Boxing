from config import PLAYERS, load_buffer


class Windower:
    def __init__(self, nn, players=PLAYERS):
        self.buffers = {p: load_buffer(nn) for p in players}

    def push(self, player, sample, t):
        return self.buffers[player].push(sample, t)
