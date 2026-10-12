from config import PLAYERS
from pairing import Pairer
from postprocessing import Postprocessor
from preprocessing import Preprocessor
from windowing import Windower


class Pipeline:
    def __init__(self, inference, monitor, players=PLAYERS):
        self.inference = inference
        self.monitor = monitor
        self.pairers = {p: Pairer() for p in players}
        self.windower = Windower(inference.nn, players)
        self.pre = Preprocessor(inference.nn)
        self.post = Postprocessor(inference.nn, self.pre, players)

    def push(self, fields):
        player = fields["player"]
        pairer = self.pairers.get(player)
        if pairer is None:
            return player, []

        self.monitor.record_packet(fields)
        paired = pairer.push(fields)
        if paired is None:
            return player, []

        sample, t = paired
        self.monitor.record_sample(player, t)
        window = self.windower.push(player, sample, t)
        if window is None:
            return player, []

        raw, stamp = window
        logits = self.inference.run(self.pre.run(raw))
        self.monitor.record_window(player)

        events = self.post.run(player, logits, raw, stamp)
        for event in events:
            self.monitor.record_event(player, event)
        return player, events
