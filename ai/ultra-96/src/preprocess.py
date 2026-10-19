#!/usr/bin/env python3
"""preprocess.py -- raw IMU samples to what the accelerator eats.

The PL begins at conv1. Everything to the left of conv1 that training did, the
PS has to do too, and this is it:

    raw (T, C) float   m/s^2 and rad/s, converted per sample from the
                       nodes' int16 counts by sample()
      -> standardise   (x - mean) / std, per channel, from norm_stats.json
      -> transpose     (T, C) -> (C, T); qacnn.forward() transposes before
                       quant_input, and the PL never reorders
      -> quantise      round-half-even to the quant_input integer domain,
                       then clamp
    -> (C, T) int8     handed to NNDriver.infer()

Both halves are load-bearing. The standardisation constants were fitted on the
training participants, so unstandardised input is not "slightly off" -- it is a
distribution the weights were never fitted against. And the quantisation is the
one transform in this whole chain with no upstream reference: golden.py
deliberately read its integers off the Brevitas quant_input hook rather than
recompute them, precisely so that nothing reimplemented it. On the board there
is no Brevitas, so this file has to. See check_against_golden() for how that
gets verified rather than assumed.

Deliberately *not* here, and each for its own reason:

  - resampling to 100 Hz and cross-node time alignment: an interface item with
    Comms, and the contract is not accepted yet
  - gravity-frame orientation normalisation: designed but not specified; it
    belongs between the raw samples and standardise()
  - stride-4 window assembly: a buffering concern, not a transform
  - argmax, confidence, intensity, debounce / non-max suppression: those act on
    logits, so they belong after infer(), not before it
"""

import json
from pathlib import Path

import numpy as np

from description import Description
from u96_config import (
    ACCEL_LSB_PER_G, BUILD_DIR, DESCRIPTION_GLOB, GRAVITY_MS2, GYRO_LSB_PER_DPS,
    NORM_STATS_NAME, one,
)


class Preprocess:
    """Standardise and quantise one window, per the build's own contract.

    Holds no hardware and imports no pynq, so it runs on a laptop. That is
    deliberate: the quantiser needs checking against the golden windows, and
    that check should not require the board.
    """

    def __init__(self, run_dir=BUILD_DIR, desc=None):
        self.run_dir = Path(run_dir)
        self.desc = desc or Description(one(DESCRIPTION_GLOB, self.run_dir))

        stats_path = self.run_dir / NORM_STATS_NAME
        if not stats_path.exists():
            raise SystemExit(
                f"{stats_path}: missing. It ships with the run -- without it "
                "the accelerator gets raw IMU units it was never trained on."
            )

        payload = json.loads(stats_path.read_text())
        self.channel_names = list(payload["channels"])
        self.mean = np.asarray(payload["mean"], dtype=np.float32)
        self.std = np.asarray(payload["std"], dtype=np.float32)

        if not len(self.channel_names) == len(self.mean) == len(self.std) == self.desc.channels:
            raise SystemExit(
                f"{stats_path.name}: {len(self.channel_names)} channels, but "
                f"{self.desc.path.name} says {self.desc.channels}. These are "
                "different builds."
            )

        self.si_scale = self._si_scale(self.channel_names)

        # quant_input: value = integer * 2**log2_scale, clamped.
        quant = self.desc.quant_input
        self.to_integer = quant.to_integer
        self.clamp_low = quant.clamp_low
        self.clamp_high = quant.clamp_high

    @staticmethod
    def _si_scale(channel_names):
        """(C,) multiplier from int16 counts to SI, read off the channel names.

        Names are <node>_<a|g><axis>, the same convention Postprocess reads its
        accelerometer channels by. Built from the names rather than assumed
        from a fixed order, so a reordered or renamed channel fails here
        instead of being silently scaled as the wrong sensor.
        """
        accel = GRAVITY_MS2 / ACCEL_LSB_PER_G
        gyro = np.pi / 180.0 / GYRO_LSB_PER_DPS
        scale = []

        for name in channel_names:
            sensor = name.partition("_")[2]
            if sensor.startswith("a"):
                scale.append(accel)
            elif sensor.startswith("g"):
                scale.append(gyro)
            else:
                raise SystemExit(
                    f"channel {name!r}: expected <node>_a<axis> or "
                    "<node>_g<axis>; cannot tell which sensor's scale it takes."
                )

        return np.asarray(scale, dtype=np.float32)

    # --- the transform ------------------------------------------------------

    def sample(self, counts):
        """One (C,) sample of MPU int16 counts -> m/s^2 and rad/s.

        Per sample, before WindowBuffer.push(), not per window: the raw window
        feeds both standardise() and Postprocess.intensity(), and both expect
        SI units. `counts` is in channel_names order.
        """
        c = np.asarray(counts, dtype=np.float32)

        if c.shape != self.si_scale.shape:
            raise SystemExit(
                f"sample {c.shape}: expected {self.si_scale.shape}, one count "
                "per channel in channel_names order."
            )

        return c * self.si_scale

    def standardise(self, raw):
        """(T, C) raw IMU -> (T, C) standardised, per channel.

        Channel order is the caller's responsibility and cannot be checked from
        the numbers: see channel_names.
        """
        x = np.asarray(raw, dtype=np.float32)
        expected = (self.desc.window, self.desc.channels)

        if x.shape != expected:
            raise SystemExit(f"raw window {x.shape}: expected {expected} as (time, channel).")

        return (x - self.mean) / self.std

    def quantise(self, standardised):
        """(C, T) or (T, C) standardised floats -> same shape int8.

        np.rint rounds half to even, which is what the export settled on
        empirically and int_model.py verified. half_up here would be one LSB
        out on half the boundary values -- invisible to argmax, and exactly the
        class of error the bit-exact checks exist to catch.

        The clamp is a clamp, not a cast: a standardised value past the
        quantizer's range saturates, where astype(int8) would wrap it into a
        wildly wrong number of the opposite sign.
        """
        scaled = np.rint(np.asarray(standardised, dtype=np.float32) * self.to_integer)

        return np.clip(scaled, self.clamp_low, self.clamp_high).astype(np.int8)

    def window(self, raw):
        """(T, C) raw IMU -> (C, T) int8, ready for NNDriver.infer().

        Transpose sits between the two steps rather than at either end because
        that is where qacnn.forward() puts it: standardisation is per channel
        on (T, C), then transpose, then quant_input.
        """
        return np.ascontiguousarray(self.quantise(self.standardise(raw).T))

    __call__ = window

    # --- checking it ---------------------------------------------------------

    def check_against_golden(self, standardised_windows, expected):
        """Does this quantiser reproduce Brevitas' quant_input hook?

        `standardised_windows` are (N, C, T) floats as training left them and
        `expected` the (N, C, T) int8 that golden.py captured from the hook.
        Equality means the reimplementation this file was forced into agrees
        with the thing it reimplemented.

        The floats are not in golden_w<N>.npz, which carries only the integers,
        so this runs where the dataset lives -- on a laptop, off the board.
        """
        got = self.quantise(standardised_windows)
        bad = np.flatnonzero(
            (got != np.asarray(expected, dtype=np.int8)).any(axis=(1, 2))
        )

        return got, bad
