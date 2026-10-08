#!/usr/bin/env python3
"""power.py -- reading the board's own power rails.

The Ultra96 carries INA226 monitors on I2C and PYNQ exposes them as rails, each
with a voltage, a current and a power sensor. This wraps that: it discovers
what the board reports rather than naming rails, because a rail list is a
property of the board revision and hardcoding one is how this file would
quietly measure the wrong thing on a different board.

Nothing here knows about the accelerator. It samples rails; what the board is
doing while it samples is the caller's business, which is what lets
measure_power.py put the same instrument against three different workloads.

Whether PYNQ exposes rails on an Ultra96-V2 at all is the first thing to find
out -- see rails_or_explain().
"""

import threading
import time

try:
    from pynq import get_rails
except ImportError:  # pragma: no cover - only on a machine without PYNQ
    get_rails = None


def _value(sensor):
    """A sensor's reading, or NaN where the board has no such sensor.

    A rail may carry only some of the three. The Ultra96 reports its SysMon
    ADC channels as rails with a voltage and nothing else, so reaching for
    .power on one is an AttributeError on None rather than a missing key.
    """
    return sensor.value if sensor is not None else float("nan")


class Reading:
    """What one rail did over one recording."""

    def __init__(self, name, watts, volts, amps):
        self.name = name
        self.watts = list(watts)
        self.volts = list(volts)
        self.amps = list(amps)

    @property
    def samples(self):
        return len(self.watts)

    @property
    def mean(self):
        return sum(self.watts) / len(self.watts) if self.watts else float("nan")

    @property
    def spread(self):
        """Peak-to-peak, not a standard deviation.

        With a handful of samples off a slow sensor, the range says more about
        whether a number is trustworthy than a deviation computed from too
        little data would.
        """
        return (max(self.watts) - min(self.watts)) if self.watts else float("nan")

    def __str__(self):
        return f"{self.name:<16} {self.mean:7.3f} W  +/-{self.spread / 2:6.3f}"


class Recording:
    """Every rail's Reading over one interval, plus how long it really took."""

    def __init__(self, readings, seconds, samples):
        self.readings = readings
        self.seconds = seconds
        self.samples = samples

    @property
    def total(self):
        """Sum across rails.

        Treat with care: whether the rails are disjoint or include an input
        rail that already contains the others is a board question, not
        something this file can know. The per-rail figures are the honest
        report; this is a convenience.
        """
        return sum(r.mean for r in self.readings.values())

    def delta(self, baseline):
        """Per-rail mean minus another recording's, as a plain dict."""
        return {
            name: reading.mean - baseline.readings[name].mean
            for name, reading in self.readings.items()
            if name in baseline.readings
        }


def combine(recordings):
    """Several Recordings of the same regime, as one.

    Interleaving means a regime is measured in blocks spread across the run
    rather than in one sitting. The samples concatenate because they are
    samples of the same thing; what is lost is the ability to say when each
    was taken, which is exactly the information the interleaving exists to
    make irrelevant.
    """
    first = recordings[0]
    readings = {}

    for name in first.readings:
        watts, volts, amps = [], [], []
        for recording in recordings:
            reading = recording.readings[name]
            watts += reading.watts
            volts += reading.volts
            amps += reading.amps
        readings[name] = Reading(name, watts, volts, amps)

    return Recording(
        readings,
        sum(r.seconds for r in recordings),
        sum(r.samples for r in recordings),
    )


def rails_or_explain():
    """The board's rails, or a failure that says what to do about it."""
    if get_rails is None:
        raise SystemExit("pynq is not installed. This runs on the board.")

    rails = get_rails()

    if not rails:
        raise SystemExit(
            "PYNQ reports no power rails on this board.\n"
            "The INA226 monitors may still be there on I2C without PYNQ\n"
            "exposing them, in which case reading them means going at the\n"
            "I2C devices directly and knowing which rail is which from the\n"
            "board schematic. Nothing downstream of this can proceed."
        )

    return rails


class PowerMonitor:
    """Polls every rail that reports power, in the foreground or alongside work.

    Rails without a power sensor are dropped rather than worked around. On the
    Ultra96-V2 those are the eleven `in*` SysMon ADC channels, which report a
    voltage and no current, so there is no wattage to be had from them and
    nothing this file can usefully do with one. They are kept in `dropped` so
    the caller can say what was ignored instead of silently reporting fewer
    rails than the board has.
    """

    def __init__(self, rails=None):
        found = rails if rails is not None else rails_or_explain()

        self.rails = {
            name: rail
            for name, rail in found.items()
            if getattr(rail, "power", None) is not None
        }
        self.dropped = sorted(set(found) - set(self.rails))

        if not self.rails:
            raise SystemExit(
                f"None of the {len(found)} rails this board reports carries a "
                "power sensor.\n"
                "Voltage alone cannot give wattage without the matching "
                "current, so\nthere is nothing to measure through PYNQ here."
            )

    def snapshot(self):
        """One reading of every rail, in watts."""
        return {name: _value(rail.power) for name, rail in self.rails.items()}

    def _collect(self, stop, interval):
        watts = {name: [] for name in self.rails}
        volts = {name: [] for name in self.rails}
        amps = {name: [] for name in self.rails}
        started = time.perf_counter()
        n = 0

        while not stop():
            for name, rail in self.rails.items():
                watts[name].append(_value(rail.power))
                volts[name].append(_value(rail.voltage))
                amps[name].append(_value(rail.current))
            n += 1

            # Sleep the remainder of the interval rather than the whole of it,
            # so the sysfs reads do not stretch the cadence.
            due = started + n * interval
            remaining = due - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

        elapsed = time.perf_counter() - started
        readings = {
            name: Reading(name, watts[name], volts[name], amps[name])
            for name in self.rails
        }

        return Recording(readings, elapsed, n)

    def record(self, seconds, interval):
        """Sample for `seconds` in this thread. The board does nothing else."""
        deadline = time.perf_counter() + seconds

        return self._collect(lambda: time.perf_counter() >= deadline, interval)

    def recording(self, interval):
        """A context manager that samples in the background while you work.

        The workload has to run in the foreground or the regime being measured
        is not the regime being described. Sensor reads are file I/O and
        release the GIL, so the sampler costs the workload very little -- but
        it is not free, and POWER_SAMPLE_INTERVAL is the knob if it shows.

        Yields a one-element list; the Recording lands in it on exit.
        """
        return _BackgroundRecording(self, interval)


class _BackgroundRecording:
    def __init__(self, monitor, interval):
        self.monitor = monitor
        self.interval = interval
        self.result = []
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(
            target=lambda: self.result.append(
                self.monitor._collect(self._stop.is_set, self.interval)
            ),
            daemon=True,
        )
        self._thread.start()

        return self.result

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()

        return False
