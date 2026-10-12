from config import load_model


class Inference:
    def __init__(self):
        self.nn = load_model()

    def run(self, window):
        return self.nn.infer(window)

    def close(self):
        self.nn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
