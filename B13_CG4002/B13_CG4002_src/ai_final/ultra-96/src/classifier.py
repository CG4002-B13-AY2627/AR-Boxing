#!/usr/bin/env python3
"""classifier.py -- the one object Comms calls.

template.py shows the four stages wired by hand. This is the same wiring,
packaged so a caller outside the AI never has to know the stages exist:

    with Classifier() as ai:
        for event in ai.push(player, sample, t):
            ...

What the caller owes us is unchanged from template.py -- per sample, the
player, NN_CH floats in the channel order desc gives, and a source timestamp.
What comes back is a list of postprocess.Event, usually empty.

Construct it on the thread that will call push(). The driver holds one pair of
DMA buffers and one accelerator, and nothing here locks around them.
"""

import asyncio
from contextlib import contextmanager

from u96_config import RUN_DIR

PLAYERS = (0, 1)


@contextmanager
def _as_runtime_error():
    """The host reports a bad build or a bad sample with SystemExit.

    That is right for a script and wrong for a library: inside a caller's
    worker thread it would take the caller's server down instead of reaching
    its error handling.
    """
    try:
        yield
    except SystemExit as exc:
        raise RuntimeError(f"AI classifier: {exc}") from exc


class Classifier:
    """Samples in, events out, for every player at once.

    One buffer and one Postprocess per player, one driver shared -- the same
    split template.py explains.
    """

    def __init__(self, run_dir=RUN_DIR, players=PLAYERS):
        self._loop = self._own_event_loop()
        self.nn = None

        try:
            with _as_runtime_error():
                # Imported here, not at the top: importing pynq may ask for an
                # event loop, and the one above has to exist first.
                from nn_driver import NNDriver
                from postprocess import Postprocess
                from preprocess import Preprocess
                from window import WindowBuffer

                self.nn = NNDriver(run_dir)
                self.pre = Preprocess(self.nn.build_dir, desc=self.nn.desc)
                self.buffers = {
                    p: WindowBuffer(self.nn.desc.window, self.nn.desc.channels)
                    for p in players
                }
                self.posts = {
                    p: Postprocess(self.nn.desc, self.pre.channel_names)
                    for p in players
                }
        except BaseException:
            self.close()
            raise

        self.windows = 0

    @staticmethod
    def _own_event_loop():
        """Give this thread an event loop if it has none, and say so.

        PYNQ asks for asyncio.get_event_loop() while it loads, which raises on
        any thread but the main one -- and asyncio.to_thread() is exactly where
        a server runs us. A fresh loop keeps us off the caller's running one.
        """
        try:
            asyncio.get_event_loop()
            return None
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    @property
    def channels(self):
        return self.nn.desc.channels

    @property
    def rate(self):
        return next(iter(self.buffers.values())).rate

    def __str__(self):
        return f"bitstream={self.nn.bitstream.name} contract={self.nn.desc}"

    def push(self, player, sample, t=None):
        """One sample for one player. The events it completed, often none.

        Three samples in four complete no window and return at once; the
        fourth costs one inference.
        """
        if player not in self.buffers:
            raise ValueError(
                f"player {player!r}: expected one of {tuple(self.buffers)}"
            )

        with _as_runtime_error():
            got = self.buffers[player].push(sample, t)
            if got is None:
                return []

            raw, stamp = got
            self.windows += 1

            _, logits = self.nn.predict(self.pre.window(raw))
            return self.posts[player].push(logits, raw, stamp)

    def reset(self, player=None):
        """Forget the stream for one player, or for all. A new round."""
        for p in self.buffers if player is None else (player,):
            self.buffers[p].reset()
            self.posts[p].reset()

    def close(self):
        try:
            if self.nn is not None:
                self.nn.close()
                self.nn = None
        finally:
            if self._loop is not None:
                try:
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                finally:
                    asyncio.set_event_loop(None)
                    self._loop.close()
                    self._loop = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
