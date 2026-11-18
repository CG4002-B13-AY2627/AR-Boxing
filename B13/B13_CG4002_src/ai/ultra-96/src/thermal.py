#!/usr/bin/env python3
"""thermal.py -- the die temperatures the board's AMS block reports.

Its own file rather than part of power.py, because it is a different sensor
reached a different way. power.py reads the INA226 rails through PYNQ's
get_rails(); the temperatures come from the ZynqMP AMS block, which the kernel
exposes as an IIO device and PYNQ does not wrap at all. power.py's own
docstring records the near miss: SysMon channels do surface through the rail
API, but with a voltage and nothing else, so there is no temperature to be had
that way.

**Why the report wants it.** The board is passively cooled and static power
rises with temperature, so a cold idle reading against a hot loaded reading
overstates the dynamic difference between them. Logging the junction
temperature at both points is what lets that objection be answered rather than
hoped away. It is §5.6.3's second promise and the reason this file exists.

Channels are discovered, never named. The board reports its AMS as `ams` on
iio:device0 with an `iio_hwmon` bridge beside two `irps5401` regulators -- but
which temperature channels that device carries, and what they are called, is a
property of the kernel's AMS driver. Reading whatever is there and labelling
each by its own channel name is both more robust and more useful, because the
name is what distinguishes the PS die from the PL die, and it is the PL one
that bears on fabric static power.
"""

import re
from pathlib import Path

from u96_config import IIO_ROOT

# The ZynqMP AMS block, as the kernel names it. Discovery falls back to any
# IIO device carrying temperature channels, so a renamed driver degrades to a
# worse label rather than to nothing.
AMS_NAME = "ams"

# in_temp0_ps_temp_raw -> index 0, label "ps_temp". The channel index orders
# the output; the label is what says which die it is.
CHANNEL = re.compile(r"^in_temp(\d+)_?(.*)$")

# IIO reports temperature as milli-degrees Celsius once scaled and offset.
MILLI = 1000.0


def _read(path):
    return path.read_text().strip()


class Channel:
    """One temperature channel, and how to turn its counts into degrees."""

    def __init__(self, path):
        """`path` is the channel's *_raw file, or its *_input file."""
        self.path = path
        name = path.name

        if name.endswith("_input"):
            self.base = name[: -len("_input")]
            self.processed = True
        else:
            self.base = name[: -len("_raw")]
            self.processed = False

        match = CHANNEL.match(self.base)
        self.index = int(match.group(1)) if match else 0
        self.label = (match.group(2) if match and match.group(2) else self.base)

    def _sibling(self, suffix, default):
        """A channel's scale or offset, or the IIO default where absent."""
        path = self.path.with_name(f"{self.base}_{suffix}")

        try:
            return float(_read(path))
        except (OSError, ValueError):
            return default

    def celsius(self):
        """This channel, in degrees Celsius.

        An *_input file is already processed; a *_raw one is counts, and the
        IIO contract is (raw + offset) * scale, in milli-degrees. Both scale
        and offset are optional, with defaults of 1 and 0, so a driver that
        publishes neither still reads correctly.
        """
        value = float(_read(self.path))

        if not self.processed:
            value = (value + self._sibling("offset", 0.0)) * self._sibling("scale", 1.0)

        return value / MILLI

    def __str__(self):
        return self.label


class Thermometer:
    """Every temperature one IIO device reports, read together."""

    def __init__(self, device, channels):
        self.device = device
        self.channels = channels

        try:
            self.name = _read(device / "name")
        except OSError:
            self.name = device.name

    @property
    def labels(self):
        return [c.label for c in self.channels]

    def read(self):
        """{label: degrees Celsius}, one pass over every channel.

        A channel that fails to read comes back as NaN rather than taking the
        others with it: one missing sensor is not a reason to lose the
        measurement the caller is in the middle of.
        """
        out = {}

        for channel in self.channels:
            try:
                out[channel.label] = channel.celsius()
            except (OSError, ValueError):
                out[channel.label] = float("nan")

        return out

    def __str__(self):
        return f"{self.name} ({', '.join(self.labels)})"


def _channels(device):
    """Every temperature channel under one IIO device, in channel order.

    A driver publishing both *_input and *_raw for the same channel would
    otherwise be read twice, so the processed form wins and the raw one is
    dropped -- it is the same sensor and *_input needs no arithmetic.
    """
    found = {}

    for path in sorted(device.glob("in_temp*")):
        if not (path.name.endswith("_raw") or path.name.endswith("_input")):
            continue

        channel = Channel(path)
        if channel.base in found and not channel.processed:
            continue
        found[channel.base] = channel

    return sorted(found.values(), key=lambda c: (c.index, c.label))


def find(root=IIO_ROOT):
    """The board's thermometer, or (None, why not).

    A tuple rather than a raise, because the caller decides how much it cares.
    measure_power.py wants the temperature but is not about to abandon a power
    measurement over a missing sensor; something written to report temperature
    alone would treat the same None as fatal. The reason travels with it either
    way, so nothing degrades silently -- the same bargain PowerMonitor strikes
    with `dropped`.
    """
    root = Path(root)

    if not root.is_dir():
        return None, f"{root} does not exist -- no IIO devices on this kernel."

    # Anything that publishes a `name`, rather than the iio:device* spelling.
    # Triggers answer that description too, but they carry no temperatures and
    # fall out below -- which is cheaper than encoding the kernel's naming and
    # being wrong about it on some other image.
    by_name = {}
    devices = []

    for device in sorted(root.iterdir()):
        try:
            by_name[_read(device / "name")] = device
            devices.append(device)
        except OSError:
            continue

    if not devices:
        return None, f"nothing under {root} publishes a `name`."

    # The AMS block first, then anything else carrying temperatures, so a
    # renamed driver still reports rather than reporting nothing.

    ordered = [by_name[AMS_NAME]] if AMS_NAME in by_name else []
    ordered += [d for d in devices if d not in ordered]

    for device in ordered:
        channels = _channels(device)
        if channels:
            return Thermometer(device, channels), None

    names = ", ".join(sorted(by_name)) or "none readable"
    return None, (
        f"no in_temp* channels on any IIO device under {root} ({names}). "
        f"The AMS driver publishes them as in_temp<N>_<die>_raw; without it "
        "there is no junction temperature to read."
    )
