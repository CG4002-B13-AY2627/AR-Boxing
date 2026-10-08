#!/usr/bin/env python3
"""pm_knobs.py -- the power knobs this board exposes. pm_guard.py puts them back.

Three of demo heading 7's four examples are knobs here: the A53 cluster
frequency, how many A53s are online, and the PL clock the accelerator runs at.
The fourth -- disabling peripherals -- is the radios, in pm_radios.py.

Every knob is the same shape: say what settings exist, read the current one,
apply another, and describe in one line what that did. Nothing here prints --
pmanagement.py owns the output, the same split verify.py has over nn_driver.

**What settings exist is read from the machine, never written down.** The
frequency steps come from cpufreq, the core list from sysfs, and the PL rates
are divisors of whatever the bitstream was built for. A board with a different
kernel, or a block design at another clock, needs no edit here.
"""

from pathlib import Path

from u96_config import CPU_ROOT, PL_CLOCK_DIVISORS


def _read(path):
    return Path(path).read_text().strip()


def _write(path, value):
    Path(path).write_text(f"{value}\n")


def _cpu_list(text):
    """A sysfs cpu list -- "0-3", "0,2-3" -- as sorted ints."""
    ids = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            ids.extend(range(int(low), int(high) + 1))
        else:
            ids.append(int(part))
    return sorted(set(ids))


class Knob:
    """One thing that can be turned down, and turned back.

    `value` is opaque and knob-specific: whatever read() returns can be handed
    to apply() unchanged. snapshot() and restore() are the same pair for the
    whole state a knob owns, which for most knobs is just the value.
    """

    name = ""
    why = ""

    def available(self):
        raise NotImplementedError

    def settings(self):
        """Every setting, most power-hungry first."""
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def apply(self, value):
        """Apply it, and return one line saying what actually happened.

        Returning the description rather than printing it keeps this file
        silent, and lets the caller narrate a demo in its own voice.
        """
        raise NotImplementedError

    def label(self, value):
        raise NotImplementedError

    def snapshot(self):
        return self.read()

    def restore(self, state):
        return self.apply(state)

    def label_state(self, state):
        return self.label(state)

    def setting_of(self, state):
        return state

    def restore_commands(self, state):
        """Shell that restores `state` without Python. See pm_guard.write_restore()."""
        raise NotImplementedError


class CpuCores(Knob):
    name = "cpu cores"
    why = "the whole A53 cluster stays powered and clocked while one core does the work"

    def __init__(self):
        self.root = CPU_ROOT
        try:
            self.present = _cpu_list(_read(self.root / "present"))
        except OSError:
            self.present = []

    def available(self):
        # cpu0 is the boot core and has no online file at all -- offlining it
        # is not a thing that can be asked for, so a board with one core has
        # no knob here rather than a knob that always fails.
        return len(self.present) > 1

    def settings(self):
        counts, n = [], len(self.present)
        while n > 1:
            counts.append(n)
            n //= 2
        counts.append(1)
        return [tuple(self.present[:n]) for n in counts]

    def read(self):
        return tuple(_cpu_list(_read(self.root / "online")))

    def _online_path(self, cpu):
        return self.root / f"cpu{cpu}" / "online"

    def apply(self, value):
        wanted = set(value) | {self.present[0]}
        changed = []

        for cpu in self.present:
            path = self._online_path(cpu)
            if not path.exists():        # cpu0 on this kernel
                continue
            state = "1" if cpu in wanted else "0"
            if _read(path) != state:
                _write(path, state)
                changed.append(("onlining" if state == "1" else "offlining", cpu))

        if not changed:
            return f"already {self.label(value)}"

        verb = changed[0][0]
        names = ", ".join(f"cpu{c}" for _, c in changed)
        return f"{verb} {names}  ->  {self.label(self.read())}"

    def label(self, value):
        return f"{len(value)} of {len(self.present)} online"

    def restore_commands(self, state):
        wanted = set(state) | {self.present[0]}
        out = []
        for cpu in self.present:
            if not self._online_path(cpu).exists():
                continue
            on = 1 if cpu in wanted else 0
            out.append(f"echo {on} | sudo tee {self._online_path(cpu)} >/dev/null")
        return out


class CpuFreq(Knob):
    name = "cpu frequency"
    why = "the cluster runs flat out and then spends most of that speed waiting on the PL"

    def __init__(self):
        self.dir = CPU_ROOT / "cpu0" / "cpufreq"

    def available(self):
        # userspace is checked rather than assumed. It happens to be the only
        # governor this kernel offers, which is itself worth knowing: nothing
        # can move the frequency underneath a measurement.
        if not self.dir.is_dir():
            return False
        try:
            return "userspace" in _read(self.dir / "scaling_available_governors").split()
        except OSError:
            return False

    def settings(self):
        steps = [int(k) for k in _read(self.dir / "scaling_available_frequencies").split()]
        return sorted(steps, reverse=True)

    def read(self):
        return int(_read(self.dir / "scaling_cur_freq"))

    def governor(self):
        return _read(self.dir / "scaling_governor")

    def apply(self, value):
        was = self.read()

        if self.governor() != "userspace":
            _write(self.dir / "scaling_governor", "userspace")

        _write(self.dir / "scaling_setspeed", value)

        # Read back: scaling_setspeed silently ignores anything that is not one
        # of the advertised steps, so the requested value is not evidence.
        now = self.read()
        if now != value:
            raise SystemExit(
                f"cpu frequency: asked for {value} kHz, got {now}. "
                f"Available: {' '.join(str(s) for s in self.settings())}."
            )
        return f"{was / 1e3:.0f} -> {self.label(value)}"

    def label(self, value):
        return f"{value / 1e3:.0f} MHz"

    def snapshot(self):
        return (self.governor(), self.read())

    def restore(self, state):
        governor, value = state
        text = self.apply(value)
        if governor != "userspace":
            _write(self.dir / "scaling_governor", governor)
        return text

    def label_state(self, state):
        governor, value = state
        return f"{self.label(value)}, {governor} governor"

    def setting_of(self, state):
        return state[1]

    def restore_commands(self, state):
        governor, value = state
        return [
            f"echo userspace | sudo tee {self.dir / 'scaling_governor'} >/dev/null",
            f"echo {value} | sudo tee {self.dir / 'scaling_setspeed'} >/dev/null",
            f"echo {governor} | sudo tee {self.dir / 'scaling_governor'} >/dev/null",
        ]


class PlClock(Knob):
    name = "pl clock"
    why = "the fabric is clocked for a deadline it already beats by a wide margin"

    def __init__(self):
        """Construct this **after** the overlay is loaded, never before.

        Overlay() re-applies the clock configuration out of the .hwh on every
        download, so a rate set before the load is silently discarded and the
        nominal read here would be whatever the previous design left behind.
        That is also why pmanagement.py owns the driver rather than calling
        bench.main().
        """
        self.nominal = self.read() if self.available() else None

    def available(self):
        try:
            from pynq import Clocks       # noqa: F401
        except ImportError:
            return False
        return True

    def settings(self):
        return [self.nominal / d for d in PL_CLOCK_DIVISORS]

    def read(self):
        from pynq import Clocks

        return float(Clocks.fclk0_mhz)

    def apply(self, value):
        from pynq import Clocks

        was = self.read()
        Clocks.fclk0_mhz = float(value)

        # PYNQ quantises to what the PLL dividers can make, so what came back
        # is the rate the fabric is really running at and the rate every
        # latency below is per.
        now = self.read()
        return f"{was:.1f} -> {now:.1f} MHz (asked {value:.1f})"

    def label(self, value):
        return f"{value:.0f} MHz"

    def restore_commands(self, state):
        return [
            "sudo -E python3 -c "
            f"'from pynq import Clocks; Clocks.fclk0_mhz = {state:.6f}'"
        ]


def board_knobs():
    return [k for k in (CpuCores(), CpuFreq(), PlClock()) if k.available()]
