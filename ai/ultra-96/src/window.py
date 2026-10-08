#!/usr/bin/env python3
"""window.py -- the sample stream to the windows the model eats.

Comms delivers a continuous stream of samples; the model classifies a fixed
32-sample window every 4 samples. This holds the ring buffer in between:

    push(sample)  x 32   -> the first window
    push(sample)  x 4    -> the next, overlapping the last by 28 samples
    ...

A buffering concern, not a transform -- which is why it is not in
preprocess.py. What comes out is still raw IMU units in (T, C); Preprocess is
what turns it into something the accelerator accepts. Keeping the two apart
means the standardise/quantise path can be checked against Brevitas without a
stream, and the stride can be checked against the contract without a model.

Deliberately not here, and each for its own reason:

  - resampling to 100 Hz and cross-node time alignment: Comms' side of a
    contract that is not accepted yet, so a sample arriving here is already
    one sample of all NN_CH channels at one instant
  - what to do about a dropped sample: same contract, and guessing now would
    bake in an assumption about a protocol nobody has agreed to
  - gravity-frame orientation normalisation: designed, not specified; it
    belongs between the raw samples and Preprocess.standardise()
"""

import numpy as np

from u96_config import SAMPLE_RATE_HZ, WINDOW_STRIDE_SAMPLES


class WindowBuffer:
    """A fixed-size ring of raw samples, emitting a window every `stride`.

    Holds no hardware and imports no pynq, so it runs on a laptop -- the same
    reason Preprocess does. The stride is a model parameter, so the buffer
    that applies it belongs to us and not to Comms.
    """

    def __init__(self, window, channels,
                 stride=WINDOW_STRIDE_SAMPLES, rate=SAMPLE_RATE_HZ):
        if not 0 < stride <= window:
            raise SystemExit(
                f"stride {stride}: must be between 1 and the window size "
                f"({window}). A stride past the window drops samples the "
                "model was never shown."
            )

        self.window = window
        self.channels = channels
        self.stride = stride
        self.rate = rate

        self._buf = np.zeros((window, channels), dtype=np.float32)
        self.reset()

    def reset(self):
        """Forget the stream. A new fight, or a resynchronisation."""
        self._buf[:] = 0.0

        # Next slot to write, and -- once the ring is full -- the oldest
        # sample in it, which is where a window has to start reading.
        self._head = 0
        self._filled = 0
        self._count = 0

        # Samples since the last emission. Starts at `stride` so that the
        # window completed by the very first full ring is emitted rather than
        # waiting a further stride for a buffer that is already valid.
        self._since = self.stride

    def samples_for(self, windows):
        """How many pushes produce `windows` windows.

        The first costs a whole window and every one after it costs a stride.
        Exists so that a caller counting windows never has to write that sum
        down -- get it wrong and a test quietly checks a different number of
        inferences than it says it does.
        """
        if windows < 1:
            raise SystemExit(f"windows {windows}: must be at least 1.")

        return self.window + (windows - 1) * self.stride

    def push(self, sample, t=None):
        """One sample in. `(window, t)` when one completes, else None.

        `window` is (T, C) raw, oldest row first. `t` is the instant of its
        most recent sample -- the window's own timestamp, and what any event
        derived from it is stamped with.

        `t` should be the timestamp Comms attached to the sample. Where there
        is none it is derived from the sample index and the contract's sample
        rate, which is a nominal clock: it cannot see a dropped packet or a
        jittery radio, so it drifts against the real one. A wall clock would be
        worse, not better -- attack and defence are classified from two
        different players' nodes and must be comparable on one timeline, which
        is the whole reason the stream is timestamped at the source.
        """
        s = np.asarray(sample, dtype=np.float32)

        if s.shape != (self.channels,):
            raise SystemExit(
                f"sample {s.shape}: expected ({self.channels},), one sample "
                "of every channel at one instant."
            )

        self._buf[self._head] = s
        self._head = (self._head + 1) % self.window
        self._filled = min(self._filled + 1, self.window)
        self._count += 1
        self._since += 1

        if t is None:
            t = (self._count - 1) / self.rate

        if self._filled < self.window or self._since < self.stride:
            return None

        self._since = 0

        return self._ordered(), t

    def _ordered(self):
        """The ring as (T, C), oldest row first.

        A copy, always: the caller holds it across the next several pushes,
        which overwrite the ring under it.
        """
        if self._head == 0:
            return self._buf.copy()

        return np.concatenate((self._buf[self._head:], self._buf[:self._head]))
