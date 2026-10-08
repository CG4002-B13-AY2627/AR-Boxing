#!/usr/bin/env python3
"""postprocess.py -- logits to the events the game engine acts on.

The mirror of preprocess.py, on the other side of the accelerator. The PL stops
at fc2 and hands back eleven raw accumulators; everything between those and
what Comms forwards to the visualizer happens here:

    (11,) int32 logits
      -> scores       softmax over logits * 2**logit_scale, the only scale
                      that makes an accumulator a number
      -> threshold    below CONFIDENCE_MIN the window is "no action", not its
                      argmax
      -> intensity    peak accelerometer magnitude above g, from the node the
                      class names
      -> debounce     one punch emits one event, not one per overlapping
                      window; a held posture emits its two edges
    -> Event, or nothing

Holds no hardware and imports no pynq, so it runs on a laptop -- the same
reason Preprocess and WindowBuffer do.

**Debounce is a leading edge, re-armed when the class goes absent, with the
refractory as a floor under it.** A timer alone cannot do this job: a punch
spans 150-250 ms and so classifies over four to six consecutive windows, while
combos arrive 200-330 ms apart, so any refractory long enough to cover one
punch is long enough to swallow the next. Measured -- six consecutive r_hook
windows fired twice at a 150 ms refractory. Requiring the class to *stop*
before it may fire again is what actually distinguishes one long punch from
two, and it is the same rule the sustained classes below already follow, which
is the argument that it is right rather than merely convenient.

The known limit: two punches of the same hand with no window between them read
as one. That is a question for the confusion matrix on real data, not one
synthetic windows can answer.

**It is not true non-maximum suppression.** NMS would buffer every candidate
for a refractory period and emit the highest-confidence one, reading the class
and the intensity off the peak of the punch rather than off its onset -- but it
cannot emit until that period has passed, so it adds the whole period to a
<= 50 ms commitment a 40 ms stride has already spent most of. The leading edge
emits on the first window that clears the threshold and costs nothing. If real
data later shows the onset window naming the wrong punch, this is the one place
that changes.
"""

import numpy as np

from u96_config import (
    CONFIDENCE_MIN,
    GRAVITY_MS2,
    IGNORED_ACTIONS,
    REFRACTORY_SECONDS,
    SUSTAINED_ACTIONS,
    SUSTAINED_RELEASE_WINDOWS,
)


class Event:
    """One thing the player did, as the game engine wants to hear it.

    `edge` is None for a discrete action, or "start"/"end" for the two ends of
    a sustained one. `intensity` is metres per second squared above gravity at
    the peak of the window, and is 0 for a release, which has none.
    """

    def __init__(self, action, t, confidence, intensity, edge=None):
        self.action = action
        self.t = t
        self.confidence = confidence
        self.intensity = intensity
        self.edge = edge

    def __str__(self):
        name = self.action if self.edge is None else f"{self.action} {self.edge}"

        return (
            f"{name} @{self.t:.3f}s  conf {self.confidence:.2f}  "
            f"intensity {self.intensity:.1f}"
        )


class Postprocess:
    """The decision logic between the accelerator and the game engine.

    Stateful across windows, deliberately: debouncing and the falling edge of
    a posture are both statements about what the previous windows said, and
    neither can be decided from one window's logits.
    """

    # Channel names are <node>_<sensor><axis> -- l_ax, r_gz. The sensor letter
    # is how the accelerometer triple is found, and the node prefix is the same
    # one the class names carry, which is what lets a left hook ask the left
    # glove how hard it was thrown.
    ACCEL = "a"

    def __init__(self, desc, channel_names,
                 confidence_min=CONFIDENCE_MIN,
                 refractory=REFRACTORY_SECONDS,
                 release=SUSTAINED_RELEASE_WINDOWS):
        self.desc = desc
        self.confidence_min = confidence_min
        self.refractory = refractory
        self.release = release

        self.sustained = tuple(SUSTAINED_ACTIONS)
        self.ignored = tuple(IGNORED_ACTIONS)

        # A class named in the config that the build does not emit means the
        # two disagree about the vocabulary, and the symptom would be silence:
        # a block that never fires an edge, or an idle that fires events.
        unknown = [a for a in self.sustained + self.ignored if a not in desc.labels]
        if unknown:
            raise SystemExit(
                f"{unknown}: named in u96_config but not in "
                f"{desc.path.name}'s labels ({desc.labels}). The config and "
                "the build disagree about the action vocabulary."
            )

        self._accel = self._accel_channels(channel_names)

        self.reset()

    @classmethod
    def _accel_channels(cls, channel_names):
        """{node: indices of its accelerometer channels}, read off the names."""
        found = {}

        for i, name in enumerate(channel_names):
            node, _, sensor = name.partition("_")
            if sensor.startswith(cls.ACCEL):
                found.setdefault(node, []).append(i)

        if not found:
            raise SystemExit(
                f"no accelerometer channels in {list(channel_names)}. Names "
                f"are expected as <node>_{cls.ACCEL}<axis>; if they were "
                "renamed, intensity has nothing to measure."
            )

        return {node: np.asarray(idx) for node, idx in found.items()}

    def reset(self):
        """Forget the stream. Pairs with WindowBuffer.reset()."""
        # When each action last fired, for the refractory floor.
        self._last = {}

        # The class the previous window settled on, or None if it cleared no
        # threshold. An action re-arms by not being this.
        self._previous = None

        # The sustained class currently held, and how many windows have gone
        # by without it.
        self._held = None
        self._absent = 0

    # --- the transforms -----------------------------------------------------

    def scores(self, logits):
        """(11,) int32 accumulators -> (11,) probabilities.

        fc2 has no quantizer after it, so a logit is integer * 2**logit_scale,
        and that scale is the only thing that makes the softmax's exponent mean
        anything. Dropping it does not merely rescale the answer: softmax is
        not scale-invariant, and a factor of 32 turns a 0.6 confidence into a
        1.0 one -- which is exactly the number CONFIDENCE_MIN gates on.
        """
        x = np.asarray(logits, dtype=np.float64) * 2.0 ** self.desc.logit_scale
        e = np.exp(x - x.max())  # shifted: exp of a raw accumulator overflows

        return e / e.sum()

    def intensity(self, raw, action):
        """How hard, in m/s^2 above gravity, from the node the class names.

        `raw` is the (T, C) window in IMU units, before standardisation --
        intensity is a physical quantity, and the standardised copy is in units
        of the training population's spread.

        A class with no node prefix -- block, pickup, idle -- takes the largest
        of the nodes, since there is no one arm to ask. Node by node, never
        across them: the magnitude of all six axes at once is sqrt(|l|^2 +
        |r|^2), which reads 13.9 for a player standing perfectly still and is
        not an acceleration anything experienced.
        """
        node = action.partition("_")[0]
        nodes = [node] if node in self._accel else list(self._accel)

        window = np.asarray(raw, dtype=np.float32)
        if window.ndim != 2 or window.shape[1] != self.desc.channels:
            raise SystemExit(
                f"raw window {window.shape}: expected (time, "
                f"{self.desc.channels}) in IMU units."
            )

        peak = max(
            np.linalg.norm(window[:, self._accel[n]], axis=1).max() for n in nodes
        )

        # Clamped at zero: free fall reads below g, and a negative intensity
        # would reach the damage calculation as a heal.
        return float(max(peak - GRAVITY_MS2, 0.0))

    # --- the decision -------------------------------------------------------

    def push(self, logits, raw, t):
        """One window's logits in, the events it caused out.

        A list, because one window can cause two: the window that ends a block
        is often the one that starts the punch thrown out of it, and dropping
        either would lose something the player really did.
        """
        p = self.scores(logits)
        top = int(np.argmax(p))
        action = self.desc.labels[top]
        confidence = float(p[top])

        confident = confidence >= self.confidence_min
        sustaining = confident and action in self.sustained
        events = []

        # Read and advance in one place, so that no return path below can
        # leave the next window judging itself against the wrong predecessor.
        previous = self._previous
        self._previous = action if confident else None

        # The falling edge first: it is a statement about the windows before
        # this one, so it has to be able to precede what this one starts.
        if self._held is not None and not (sustaining and action == self._held):
            self._absent += 1

            if self._absent >= self.release:
                held = self._held
                self._held = None

                # Confidence that it ended, not confidence in whichever class
                # ended it: those are different questions, and the consumer
                # asked the first.
                ended = float(1.0 - p[self.desc.labels.index(held)])
                events.append(Event(held, t, ended, 0.0, "end"))

        if sustaining:
            if self._held is None:
                self._held = action
                self._absent = 0
                events.append(
                    Event(action, t, confidence, self.intensity(raw, action), "start")
                )
            else:
                self._absent = 0

            return events

        if not confident or action in self.ignored or action in self.sustained:
            return events

        # Still going. One punch, however many windows it takes.
        if action == previous:
            return events

        last = self._last.get(action)
        if last is not None and t - last < self.refractory:
            return events

        self._last[action] = t
        events.append(Event(action, t, confidence, self.intensity(raw, action)))

        return events
