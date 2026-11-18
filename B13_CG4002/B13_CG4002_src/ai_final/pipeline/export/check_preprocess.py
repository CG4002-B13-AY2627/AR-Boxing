"""The one transform in the chain with nothing above it to check against.

golden.py's boundary() reads its input integers off the Brevitas quant_input
hook rather than recomputing them, on the stated grounds that reimplementing
input quantization there would put it in the one place nothing downstream could
catch. On the board there is no Brevitas, so ultra-96/src/preprocess.py had to
reimplement it anyway, and until this file existed nothing caught that either:
csim, cosim and verify.py are all handed windows that were already quantized,
so all three agree happily with a quantizer that is wrong.

This closes it from the other side. The same windows, standardised as training
left them, go through the board's own quantise() and are compared to what the
hook produced -- which is the same array golden.py ships. Exact equality, the
same standard as everywhere else in the chain.

It imports Preprocess from ultra-96/src/ rather than copying it. A check
against a second implementation would only prove that the two copies agree.

A library, like int_model.py: check.py runs it and holds the output.
"""
import sys

import numpy as np

import check_config

from export_config import train_config

# preprocess.py and description.py import each other by bare name, the way they
# do on the board, so their directory has to be on the path before either is
# reachable. Kept here rather than in export_config.py: this is the only thing
# in the export that reaches across into the board code.
if str(check_config.U96_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(check_config.U96_SRC_DIR))

from description import Description  # noqa: E402
from normalize import load_stats  # noqa: E402
from preprocess import Preprocess  # noqa: E402


class PreprocessCheck:
    """The board's pre-processing, run where Brevitas is available to judge it."""

    def __init__(self, description, checkpoint, run_dir=None):
        # The description is passed in rather than read off disk because there
        # is nothing on disk yet: check runs before export writes one.
        # Preprocess then needs only norm_stats.json out of run_dir, and
        # train/checkpoints/ is where training leaves it.
        self.run_dir = run_dir or train_config.CHECKPOINT_DIR
        self.preprocess = Preprocess(
            run_dir=self.run_dir,
            desc=Description(checkpoint, payload=description),
        )

    @property
    def stats_path(self):
        return self.preprocess.run_dir / train_config.NORM_STATS_NAME

    def check(self, standardised, expected):
        """(N, C, T) standardised floats against the hook's (N, C, T) integers.

        Returns (got, bad): what quantise() produced, and the indices of the
        windows where that is not what Brevitas produced.
        """
        return self.preprocess.check_against_golden(standardised, expected)

    def check_stats(self):
        """Which standardisation constants differ from the ones training fitted.

        Free, and worth taking. preprocess.py reads norm_stats.json out of the
        run directory while normalize.py reads it out of train/checkpoints/.
        Pointed at an archived run those are two files, and this is the only
        thing anywhere that would notice a shipped copy belonging to a
        different training run than the weights beside it. Pointed at the
        default they are one file, and this checks only that the two readers
        agree on what it says.

        Returns the names that differ, so an empty list is a pass.
        """
        fitted = load_stats()
        differ = []

        # Not checkable from the numbers: nothing downstream knows what order
        # the nodes report their channels in, so a permutation here is silent.
        if self.preprocess.channel_names != list(train_config.FEATURE_COLUMNS):
            differ.append("channels")

        if not np.array_equal(self.preprocess.mean, fitted["mean"].numpy()):
            differ.append("mean")

        if not np.array_equal(self.preprocess.std, fitted["std"].numpy()):
            differ.append("std")

        return differ
