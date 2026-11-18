#!/usr/bin/env python3
"""nn_driver.py -- the only file on the board that touches hardware.

Loads the overlay this run shipped with, moves one 32x12 window across HP0
into the accelerator, and hands back the 11 raw logits it produced.

Every path, glob and register offset comes from u96_config.py; every dimension
comes from description_w<N>.json. Re-exporting at another width and re-sending
should need no edit here.

Defines NNDriver and nothing else. The diagnostics that used to live here
are in verify.py, which is where everything printable was gathered.
"""

from pathlib import Path
from time import perf_counter

import numpy as np
from pynq import Overlay, allocate

from description import Description
from u96_config import (
    AP_DONE,
    AP_START,
    BITSTREAM_GLOB,
    BUILD_DIR_NAME,
    CTRL,
    DESCRIPTION_GLOB,
    HWH_SUFFIX,
    IN_PORT,
    IP_PREFIX,
    OUT_PORT,
    PTR_HI,
    PTR_LO,
    RUN_DIR,
    one,
)


class NNDriver:
    """One loaded overlay, one pair of DMA buffers, one window at a time."""

    def __init__(self, run_dir=RUN_DIR):
        self.run_dir = Path(run_dir)
        self.build_dir = self.run_dir / BUILD_DIR_NAME
        self.bitstream = one(BITSTREAM_GLOB, self.build_dir)
        self.desc = Description(one(DESCRIPTION_GLOB, self.build_dir))

        # Overlay() reads the .hwh of the same basename beside the .bit --
        # that is where the register map below comes from.
        if not self.bitstream.with_suffix(HWH_SUFFIX).exists():
            raise SystemExit(f"{self.bitstream}: no {HWH_SUFFIX} beside it.")
        self.overlay = self._load()
        self.ip = self._find_ip()
        self.mmio = self.ip.mmio

        # Allocated once and reused. Allocating per inference would make
        # bench.py measure the allocator instead of the accelerator.
        self.x = allocate(shape=(self.desc.in_len,), dtype=np.int8)
        self.y = allocate(shape=(self.desc.classes,), dtype=np.int32)

        self._write_pointer(IN_PORT, self.x)
        self._write_pointer(OUT_PORT, self.y)

    @staticmethod
    def _clear_stale_state():
        """Drop PYNQ's record of the last-loaded bitstream, before loading ours.

        PYNQ caches which bitstream was last loaded in a global state file. If
        that file names a .bit that has since moved or been deleted -- which is
        what every re-transfer, rename or rm -rf of a run directory does --
        hashing it throws, and PYNQ reports the failure against *our* file as
        "Unable to parse metadata". The build is fine; the cache is stale.

        So drop it rather than explain it afterwards. Nothing is lost: the load
        on the next line reprograms the PL and writes the state fresh. The cost
        is that a second run in a row reprograms instead of skipping, which is
        about a second and buys never seeing that message again.

        Best effort on purpose. If the module moved in a later PYNQ, or the
        state is not ours to delete because this is not running under sudo,
        that is not a reason to refuse to load -- Overlay() below is still what
        decides, and its handler still prints the manual command.
        """
        try:
            from pynq.pl_server.global_state import clear_global_state

            clear_global_state()
        except Exception:
            pass

    def _load(self):
        """Program the PL, translating one misleading PYNQ failure.

        The stale-cache failure this used to only explain is now pre-empted by
        _clear_stale_state(). The handler stays as the net for the case where
        clearing could not run.
        """
        self._clear_stale_state()

        try:
            return Overlay(str(self.bitstream))
        except RuntimeError as exc:
            if "metadata" not in str(exc).lower():
                raise
            raise SystemExit(
                f"{self.bitstream.name}: Overlay() could not parse metadata.\n"
                "PYNQ's global state was already cleared before this load, so "
                "the usual cause is ruled out unless the clear itself failed "
                "-- which it does silently when this is not run under sudo. "
                "Check that first, by hand:\n"
                "  sudo -E python3 -c 'from pynq.pl_server.global_state "
                "import clear_global_state; clear_global_state()'\n"
                "If that succeeds and this still fails, the .bit and .hwh are "
                "the suspects, not the cache."
            ) from exc

    def _find_ip(self):
        names = [n for n in self.overlay.ip_dict if n.startswith(IP_PREFIX)]
        if len(names) != 1:
            raise SystemExit(
                f"{self.bitstream.name}: expected one {IP_PREFIX} IP, "
                f"found {names or 'none'}."
            )
        return getattr(self.overlay, names[0])

    def _write_pointer(self, port, buf):
        """Hand the PL a buffer's physical address, low half then high."""
        rmap = self.ip.register_map
        addr = int(buf.device_address)

        if not hasattr(rmap, port + PTR_LO):
            visible = [n for n in dir(rmap) if not n.startswith("_")]
            raise SystemExit(
                f"{port + PTR_LO}: not in the register map ({visible}). "
                "The .hwh does not match the interface nn_driver expects."
            )

        setattr(rmap, port + PTR_LO, addr & 0xFFFFFFFF)
        setattr(rmap, port + PTR_HI, (addr >> 32) & 0xFFFFFFFF)

    def infer(self, window, phases=None):
        """One window in, raw logits out. No softmax, no scaling.

        `phases`, if given, is a list this call appends one
        (copy, flush, wait, invalidate) tuple of seconds to. It exists so
        bench.py can attribute host overhead without keeping a second copy of
        this sequence that could drift out of step with the real one. When it
        is None -- every path but the benchmark -- the cost is four branches.
        """
        w = np.ascontiguousarray(window)

        if w.shape not in {(self.desc.channels, self.desc.window), (self.desc.in_len,)}:
            raise SystemExit(
                f"window {w.shape}: expected "
                f"({self.desc.channels}, {self.desc.window}) or ({self.desc.in_len},)."
            )

        # Channel-major, in[c * window + t] -- params_w<N>.hpp is explicit
        # about this and the golden windows are already (C, T), so a C-order
        # reshape is the layout the PL was built for. Do not transpose.
        timed = phases is not None
        t0 = perf_counter() if timed else 0.0

        self.x[:] = w.reshape(-1).astype(np.int8, copy=False)
        t1 = perf_counter() if timed else 0.0

        self.x.flush()  # HP0 is not cache-coherent: push before ap_start
        t2 = perf_counter() if timed else 0.0

        self.mmio.write(CTRL, AP_START)

        # ap_done is clear-on-read under ap_ctrl_hs, so the read that observes
        # it also clears it -- which is what the next ap_start needs. Busy-wait
        # rather than sleep: one inference is ~1.1 ms and a sleep would cost
        # more than it saves.
        while not self.mmio.read(CTRL) & AP_DONE:
            pass
        t3 = perf_counter() if timed else 0.0

        self.y.invalidate()  # ...and pull after, for the same reason
        if timed:
            phases.append((t1 - t0, t2 - t1, t3 - t2, perf_counter() - t3))

        return np.array(self.y)  # copy: the buffer is about to be reused

    def predict(self, window):
        """(label, logits) for callers that want the class, not the numbers."""
        logits = self.infer(window)
        return self.desc.labels[int(np.argmax(logits))], logits

    def close(self):
        for buf in (self.x, self.y):
            buf.freebuffer()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
