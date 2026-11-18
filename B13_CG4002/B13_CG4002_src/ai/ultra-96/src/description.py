"""description_w<N>.json -- the host's half of the interface contract.

Its own module rather than a class inside nn_driver.py, because preprocess.py
needs the same contract and importing nn_driver would drag in pynq: the
pre-processing has nothing to do with hardware and must stay runnable, and
testable, off the board.
"""

import json
from pathlib import Path


class QuantSpec:
    """One activation quantizer, as extract.py described it.

    value = integer * 2**log2_scale, clamped to [clamp_low, clamp_high].
    """

    def __init__(self, name, payload):
        self.name = name
        self.log2_scale = payload["log2_scale"]
        self.bit_width = payload["bit_width"]
        self.signed = payload["signed"]
        self.clamp_low = payload["clamp_low"]
        self.clamp_high = payload["clamp_high"]

    @property
    def to_integer(self):
        """Multiply a real value by this to reach the integer domain."""
        return 2.0 ** -self.log2_scale

    def __str__(self):
        return (
            f"{self.name}: scale 2^{self.log2_scale}, "
            f"{self.bit_width} bits, [{self.clamp_low}, {self.clamp_high}]"
        )


class Description:
    """Everything the host needs to know about the build it is driving."""

    def __init__(self, path, payload=None):
        self.path = Path(path)

        # payload is for a description that is not on disk yet. check.py runs
        # before export.py has dumped one -- deliberately, so that headers are
        # never emitted from arithmetic that failed -- and must check what
        # extract() produces now rather than an older json left over from a
        # previous checkpoint. `path` is then the checkpoint it was extracted
        # from, which is what the failures below want to name anyway.
        if payload is None:
            payload = json.loads(self.path.read_text())

        meta = payload["meta"]
        self.sha256 = meta["sha256"]
        self.checkpoint = meta["checkpoint"]
        self.width = meta["bit_width"]
        self.window = meta["window_size"]
        self.channels = meta["num_channels"]
        self.classes = meta["num_classes"]
        self.labels = list(meta["labels"])

        # The quantizer sitting at the PS/PL boundary. Everything to its left
        # is preprocess.py's job; the PL starts to its right.
        self.quant_input = QuantSpec("quant_input", payload["activations"]["quant_input"])

        # ...and the scale at the other boundary, where the PL stops. The
        # output layer emits raw accumulators with no quantizer after it, so
        # logits reach the host as integers meaning integer * 2**logit_scale.
        # postprocess.py needs it to take a softmax over anything meaningful.
        # Found by which layer has no output activation rather than by
        # position, so adding a layer cannot silently move it.
        self.logit_scale = self._output_scale(payload)

        if len(self.labels) != self.classes:
            raise SystemExit(
                f"{self.path}: {len(self.labels)} labels for "
                f"{self.classes} classes."
            )

    @staticmethod
    def _output_scale(payload):
        """log2 of the scale on the final layer's accumulators."""
        tail = [L for L in payload["layers"] if L["output_activation"] is None]

        if len(tail) != 1:
            raise SystemExit(
                f"expected exactly one layer with no output activation, "
                f"found {len(tail)}. Which one produces the logits is then a "
                "guess, and a wrong scale makes every confidence wrong."
            )

        return tail[0]["accumulator_log2_scale"]

    @property
    def in_len(self):
        """Flat length of the input buffer. in[c * window + t], channel-major."""
        return self.channels * self.window

    def __str__(self):
        return (
            f"{self.checkpoint} w{self.width}  "
            f"{self.channels}ch x {self.window} -> {self.classes} classes  "
            f"sha {self.sha256[:12]}"
        )
