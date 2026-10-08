#!/usr/bin/env python3
"""template.py -- the shape of an integration against the accelerator.

Copy this, replace source() and sink(), delete what is left. It is the only
file here that is meant to be edited rather than run as shipped: everything
under src/ is the host, and this is an example of driving it.

Unlike the rest of the host code it lands at the run root, beside the
bitstream, because it is a starting point for the caller rather than part of
the library the caller uses. transfer.sh puts it there.

    cd ~/ai/<run> && sudo -E python3 template.py

sudo, because loading an overlay needs root; -E, because PYNQ lives in a
virtualenv at /usr/local/share/pynq-venv that a plain sudo would drop. Same
invocation verify.sh uses.

The four stages and the order data moves through them:

    WindowBuffer   a ring of raw samples, one (32, 12) window every 4
    Preprocess     standardise, transpose to channel-major, quantise to int8
    NNDriver       the only thing here that touches hardware
    Postprocess    eleven logits to an Event, or to nothing

What the caller owes us, per sample:

    player  which of the two, so their windows and debounce stay apart
    sample  NN_CH floats at one instant, in the channel order desc gives --
            l_ax l_ay l_az l_gx l_gy l_gz r_ax r_ay r_az r_gx r_gy r_gz
    t       seconds, stamped at the source. Attack and defence are classified
            from two players' nodes and are compared against each other, so a
            timestamp applied on arrival here measures our own queueing delay
            rather than when the punch happened.

Resampling to a common grid, cross-node alignment and dropped samples are
deliberately not handled anywhere in the host -- they are the other side of an
input contract that has not been agreed. A sample reaching push() is assumed
to be every channel at one instant.
"""

import sys
import time
from pathlib import Path

# src/ holds the host; this file does not live in it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import numpy as np

from nn_driver import NNDriver
from postprocess import Postprocess
from preprocess import Preprocess
from window import WindowBuffer

PLAYERS = 2


def source(channels, rate):
    """REPLACE. Yield (player, sample, t) as samples arrive from Comms.

    The placeholder below is noise, so the labels it produces mean nothing.
    It is here so the wiring can be run before Comms exists.
    """
    rng = np.random.default_rng(0)

    for index in range(2000):
        sample = rng.standard_normal(channels).astype(np.float32) * 4.0
        yield index % PLAYERS, sample, index / rate


def sink(player, event):
    """REPLACE. Hand one action to Comms for the visualizer."""
    print(f"player {player}  {event}")


def main():
    with NNDriver() as nn:
        pre = Preprocess(nn.build_dir, desc=nn.desc)

        # One buffer and one Postprocess per player. Sharing either would let
        # one player's stride offset and debounce state suppress the other's
        # punches. The driver is shared -- there is one accelerator, calls to
        # it serialise, and at a 6.8 % duty cycle two players do not contend.
        buffers = [
            WindowBuffer(nn.desc.window, nn.desc.channels)
            for _ in range(PLAYERS)
        ]
        posts = [
            Postprocess(nn.desc, pre.channel_names)
            for _ in range(PLAYERS)
        ]

        print(f"bitstream  {nn.bitstream.name}")
        print(f"contract   {nn.desc}")
        print(f"players    {PLAYERS}\n")

        started = time.perf_counter()
        windows = 0
        events = 0

        for player, sample, t in source(nn.desc.channels, buffers[0].rate):
            got = buffers[player].push(sample, t)

            # Three samples in four. The stride is 4, the window is 32.
            if got is None:
                continue

            raw, stamp = got
            windows += 1

            # predict() returns (label, logits); Postprocess wants the logits,
            # and raw for the intensity it reads off the accelerometer.
            _, logits = nn.predict(pre.window(raw))

            for event in posts[player].push(logits, raw, stamp):
                events += 1
                sink(player, event)

        elapsed = time.perf_counter() - started
        print(f"\n{windows} windows, {events} events, {elapsed:.2f} s")


if __name__ == "__main__":
    main()
