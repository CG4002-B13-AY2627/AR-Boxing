from config import load_preprocess


class Preprocessor:
    def __init__(self, nn):
        self.pre = load_preprocess(nn)

    @property
    def channel_names(self):
        return self.pre.channel_names

    def run(self, raw):
        return self.pre.window(raw)
