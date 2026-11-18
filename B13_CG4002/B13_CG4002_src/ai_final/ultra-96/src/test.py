#!/usr/bin/env python3
"""test.py -- the whole PS path end to end, on dummy data or on a shipped segment.

A stream of raw samples through WindowBuffer, Preprocess, NNDriver and
Postprocess to action events. It exercises every join between the four, which
nothing else does: verify.py replays windows that were already quantised, so
neither the buffering nor the pre-processing nor the decision logic runs there.

Which stream depends on whether the run holds a sample/ directory:

  - **none** -- dummy data. **This tests plumbing, not correctness.** The data
    is random, so the labels it prints mean nothing -- what it proves is that
    the stream windows at the right offsets, the transform produces something
    the accelerator accepts, the logits come back scaled into usable scores,
    and events fall out the far end. Correctness lives in verify.py, which has
    ground truth to compare against.
  - **sample/segment.txt** -- a stretch of real IMU rows, drawn and sent from
    the laptop by individual-subcomponent-test/scripts/sample. Every window's
    raw logits and predicted class are printed as a table and saved beside the
    segment as hardware_logits.txt. The laptop runs the same segment through
    the Brevitas checkpoint and renders the same table with logit_table.py, so
    the two agree to the digest on the last line or the hardware is wrong.
    The window count comes from the segment, not from the argument.

Two things here *are* checked rather than printed, because they have an answer
that does not depend on the data: each emitted window must equal its own slice
of the stream exactly, and it must carry the timestamp of its last sample.
Those are the claims WindowBuffer makes, and they are cheap to hold it to.

    python3 test.py         four windows, or the whole segment
    python3 test.py 10      ten, when there is no segment
"""

import sys

import numpy as np

from logit_table import render
from nn_driver import NNDriver
from postprocess import Postprocess
from preprocess import Preprocess
from segment import find, load
from u96_config import HARDWARE_TABLE_NAME
from window import WindowBuffer

SEED = 0

# Enough to see the ring buffer wrap, the stride hold, and the refractory
# have something to suppress. One window would test none of them.
WINDOWS = 4

# Runners-up printed beside the winner.
RUNNERS = 3


def dummy_stream(pre, rng, samples):
    """(samples, channels) of plausible raw IMU units -- m/s^2 and rad/s.

    Drawn around the training distribution rather than from unit noise. Raw
    accelerometer channels sit near 9.8 where gravity falls, so a standard
    normal in raw units would standardise to about -5 and saturate the
    quantizer on every sample, which would test nothing but the clamp.

    Using the same mean and std the transform divides by is mildly circular.
    That is fine here: the point is to hand the accelerator something shaped
    like real input, not to check the statistics.

    One stream, not one window per inference -- the windows have to overlap or
    the stride is never exercised.
    """
    shape = (samples, pre.desc.channels)

    return (pre.mean + pre.std * rng.standard_normal(shape)).astype(np.float32)


def classify(nn, pre, buf, stream):
    seen = 0
    for i, sample in enumerate(stream):
        got = buf.push(sample)
        if got is None:
            continue

        raw, t = got
        seen += 1

        # The two claims WindowBuffer makes. A window assembled from the
        # wrong slice, or out of order, would still be the right shape and
        # would still classify -- it would just classify the wrong motion,
        # and nothing downstream could ever tell.
        start = i - buf.window + 1
        if not np.array_equal(raw, stream[start:i + 1]):
            raise SystemExit(
                f"window {seen}: does not match stream[{start}:{i + 1}]. "
                "The ring buffer is assembling samples out of order."
            )
        if abs(t - i / buf.rate) > 1e-9:
            raise SystemExit(
                f"window {seen}: stamped {t:.6f}s, but its last sample is "
                f"{i} at {i / buf.rate:.6f}s."
            )

        quantised = pre.window(raw)
        label, logits = nn.predict(quantised)

        yield seen, start, i, raw, t, quantised, label, logits


def dummy(nn, pre, buf, windows):
    rng = np.random.default_rng(SEED)
    post = Postprocess(nn.desc, pre.channel_names)

    samples = buf.samples_for(windows)
    stream = dummy_stream(pre, rng, samples)

    print(f"bitstream  {nn.bitstream.name}")
    print(f"contract   {nn.desc}")
    print(f"stream     {samples} samples x {nn.desc.channels} channels, "
          f"window {buf.window} stride {buf.stride} at {buf.rate} Hz")
    print(f"gates      confidence >= {post.confidence_min:.2f}, "
          f"refractory {post.refractory * 1e3:.0f} ms\n")

    seen = 0
    fired = 0
    for seen, start, i, raw, t, quantised, label, logits in classify(nn, pre, buf, stream):
        scores = post.scores(logits)
        events = post.push(logits, raw, t)

        order = np.argsort(scores)[::-1]
        runners = ", ".join(
            f"{nn.desc.labels[j]} {scores[j]:.3f}"
            for j in order[1:1 + RUNNERS]
        )

        print(f"window {seen}/{windows}  stream[{start}:{i + 1}]  t {t:.3f}s")
        print(f"  raw      [{raw.min():.2f}, {raw.max():.2f}] IMU units")
        print(f"  window   {quantised.shape} {quantised.dtype}, "
              f"[{quantised.min()}, {quantised.max()}] quantised")
        print(f"  logits   {logits.tolist()}")
        print(f"  ->       {label}  score {scores[order[0]]:.3f}")
        print(f"  then     {runners}")

        for event in events:
            print(f"  event    {event}")
        fired += len(events)
        print()

    if seen != windows:
        raise SystemExit(
            f"{samples} samples produced {seen} windows, not {windows}. "
            "samples_for() and push() disagree about the stride."
        )

    # Either count is a pass. Random windows usually put nothing above the
    # threshold, but they are not required to -- an untrained-for input can
    # land confidently on some class, and that is the debounce being
    # exercised rather than anything going wrong. Say which happened, so
    # the reader is not left deciding whether silence was the point.
    print(f"{seen} windows, each matching its slice of the stream.")
    if fired:
        print(f"{fired} event(s) from {seen} windows: fewer than one per "
              "window is the debounce working.")
    else:
        print(f"No events: eleven classes over random data seldom put "
              f"{post.confidence_min:.0%} on any one of them.")


def sampled(nn, pre, buf, path):
    segment = load(path, nn.desc.window, nn.desc.channels)
    logits = [got[-1] for got in classify(nn, pre, buf, segment)]

    table = render(f"hardware  {nn.bitstream.name}", segment,
                   buf.window, buf.stride, nn.desc.labels, logits)
    out = path.parent / HARDWARE_TABLE_NAME
    out.write_text(table)

    print(table)
    print(f"saved     {out}")


def main(windows=WINDOWS):
    with NNDriver() as nn:
        pre = Preprocess(nn.build_dir, desc=nn.desc)
        buf = WindowBuffer(nn.desc.window, nn.desc.channels)

        path = find()
        if path is None:
            dummy(nn, pre, buf, windows)
        else:
            sampled(nn, pre, buf, path)


if __name__ == "__main__":
    arg = WINDOWS
    if len(sys.argv) > 1:
        try:
            arg = int(sys.argv[1])
        except ValueError:
            raise SystemExit(f"usage: {sys.argv[0]} [n_windows]")
    main(arg)
