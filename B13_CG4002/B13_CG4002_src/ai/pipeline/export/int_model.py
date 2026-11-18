"""A bit-exact reference implementation of the quantized CNN, in NumPy integers.

extract.py derives a shift and a pair of clamp bounds for every layer, and
asserts a good deal about them. This is what tests those assertions: it runs
the network using plain integer arithmetic and compares every intermediate
against the Brevitas/PyTorch model the description was extracted from.

A library, not a script. check.py runs it, holds every line of output, and
hands it the Brevitas side to compare against -- the same arrangement as the
board's verify.py over nn_driver.py and preprocess.py. Nothing here prints;
what comes back is counts and arrays.
"""
from collections import namedtuple

import numpy as np

import export_config

from export_config import train_config

def rshift(value, shift, mode):

    # Check for negative shift
    if shift < 0:
        raise SystemExit(f"negative shift {shift}: extract.py should have caught this.")

    # No shift, value is just itself.
    if shift == 0:
        return value

    if mode == "trunc":
        # An arithmetic shift, this floors rather than truncating towards zero.
        return value >> shift

    half = np.int64(1) << np.int64(shift - 1)

    if mode == "half_up":
        return (value + half) >> shift

    if mode == "half_even":
        quotient = (value + half) >> shift
        # The discarded low bits, read off the two's complement pattern,
        # This stays correct for negative values.
        discarded = value & ((np.int64(1) << np.int64(shift)) - 1)

        # Elementwise, not a single bool: every position decides its own tie,
        # and np.where below expects a mask the same shape as the accumulator.
        tie = discarded == half

        return np.where(tie & ((quotient & 1) == 1), quotient - 1, quotient)

    raise SystemExit(f"Unknown rounding mode {mode}")

def requantize(accumulator, shift, low, high, mode):
    return np.clip(rshift(accumulator, shift, mode), low, high)

def conv1d(x, weight, bias):
    in_channels, time = x.shape
    out_channels, _, kernel = weight.shape

    total_padding = kernel - 1
    pad_left = total_padding // 2
    pad_right = total_padding - pad_left

    padded = np.zeros(
        (in_channels, time + pad_left + pad_right),
        dtype=np.int64,
    )
    padded[:, pad_left:pad_left + time] = x

    accumulator = np.zeros((out_channels, time), dtype=np.int64) + bias[:, None]

    for o in range(out_channels):
        for i in range(in_channels):
            for k in range(kernel):
                accumulator[o] += weight[o, i, k] * padded[i, k:k + time]

    return accumulator

def maxpool1d(x, kernel, stride):
    if kernel != stride:
        # This is just to ensure that there is no overlapping of the kernel while we maxpool
        raise SystemExit("this reshape assumes non-overlapping windows.")

    channels, time = x.shape
    out = time // stride

    return x[:, :out * stride].reshape(channels, out, stride).max(axis=2)

def linear(x, weight, bias):
    return weight @ x + bias


# One failing window, reduced to what a reader needs: which stage broke first,
# how much of it, and by how far. A max_diff of one everywhere points at the
# rounding mode; a few differing elements point at a clamp bound.
Mismatch = namedtuple("Mismatch", "sample stage differing size max_diff")


def mismatch(sample, stage, got, want):
    difference = np.abs(got - want)

    return Mismatch(
        sample=sample,
        stage=stage,
        differing=int((difference != 0).sum()),
        size=int(difference.size),
        max_diff=int(difference.max()),
    )


class IntegerModel:
    """The exported description, executed as integers and nothing else."""

    def __init__(self, description, mode):
        self.description = description
        self.mode = mode
        self.layers = {layer["name"]: layer for layer in description["layers"]}

    def parameters(self, name):
        layer = self.layers[name]

        return (
            np.array(layer["weight"], dtype=np.int64),
            np.array(layer["bias"], dtype=np.int64),
            layer,
        )

    def requantize(self, accumulator, spec):
        return requantize(
            accumulator=accumulator,
            shift=spec["shift"],
            low=spec["clamp_low"],
            high=spec["clamp_high"],
            mode=self.mode,
        )

    @property
    def budget(self):
        """The accumulator bits extract.py sized each layer for."""
        budget = {
            layer["name"]: layer["accumulator_bits_required"]
            for layer in self.description["layers"]
        }
        # The pool sizes its own accumulator now, so it is no longer a blank row.
        budget["pool"] = self.description["global_pool"]["accumulator_bits_required"]

        return budget

    def forward(self, window):
        """One quantized window in, raw fc2 accumulators out.

        Returns the logits, the trace of every quantizer output along the way,
        and the largest accumulator each layer reached.
        """
        trace = {"quant_input": window}
        peaks = {}

        # Convolution number 1
        weight, bias, layer = self.parameters("conv1")
        accumulator = conv1d(
            x=window,
            weight=weight,
            bias=bias
        )
        peaks["conv1"] = int(np.abs(accumulator).max())
        x = self.requantize(accumulator, layer)
        trace["relu1"] = x

        x = maxpool1d(
            x=x,
            kernel=train_config.POOL_KERNEL,
            stride=train_config.POOL_STRIDE
        )

        # Convolution number 2
        weight, bias, layer = self.parameters("conv2")
        accumulator = conv1d(
            x=x,
            weight=weight,
            bias=bias
        )
        peaks["conv2"] = int(np.abs(accumulator).max())
        x = self.requantize(accumulator, layer)
        trace["relu2"] = x

        accumulator = x.sum(axis=1)
        peaks["pool"] = int(np.abs(accumulator).max())
        x = self.requantize(accumulator, self.description["global_pool"])
        trace["quant_pool"] = x

        # fc1
        weight, bias, layer = self.parameters("fc1")
        accumulator = linear(
            x=x,
            weight=weight,
            bias=bias
        )
        peaks["fc1"] = int(np.abs(accumulator).max())
        x = self.requantize(accumulator, layer)
        trace["relu3"] = x

        # fc2
        weight, bias, layer = self.parameters("fc2")
        logits = linear(
            x=x,
            weight=weight,
            bias=bias
        )
        peaks["fc2"] = int(np.abs(logits).max())

        return logits, trace, peaks

    def check(self, captured, expected_logits):
        """Every window through the integer model, against what Brevitas did.

        `captured` is each quantizer's output keyed by name, `expected_logits`
        the float logits already divided down to fc2's accumulator scale. Both
        come from check.py's one Brevitas pass.

        Returns (mismatches, peaks): one Mismatch per failing window, and the
        largest accumulator every layer reached across all of them.
        """
        mismatches = []
        peaks = {}

        for sample in range(len(expected_logits)):
            logits, trace, sample_peaks = self.forward(captured["quant_input"][sample])

            for name, value in sample_peaks.items():
                peaks[name] = max(peaks.get(name, 0), value)

            # Stage by stage, in network order. The first mismatch names one
            # shift and one loop; a mismatch only at the logits names nothing.
            for name in export_config.ACTIVATIONS:
                if not np.array_equal(trace[name], captured[name][sample]):
                    mismatches.append(
                        mismatch(sample, name, trace[name], captured[name][sample])
                    )
                    break
            else:
                if not np.array_equal(logits, expected_logits[sample]):
                    mismatches.append(
                        mismatch(sample, "logits", logits, expected_logits[sample])
                    )

        return mismatches, peaks
