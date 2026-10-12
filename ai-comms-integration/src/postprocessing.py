from config import PLAYERS, load_postprocess


class Postprocessor:
    def __init__(self, nn, pre, players=PLAYERS):
        self.posts = {p: load_postprocess(nn, pre) for p in players}

    def run(self, player, logits, raw, t):
        return self.posts[player].push(logits, raw, t)
