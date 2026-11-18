import numpy as np

import convert_config as cc

from recording import Rep


def resampled(reps, count, rng):
    if not count:
        return []
    if not reps:
        raise SystemExit("Cannot resample an empty cell.")

    first = reps[0]
    width = first.signal.shape[1]
    donors = rng.integers(len(reps), size=(count, width))

    return [
        Rep(
            first.participant, first.label, cc.RESAMPLED, first.participant, (None, None),
            np.column_stack([reps[donor].signal[:, channel] for channel, donor in enumerate(row)]),
            tuple(reps[donor].rows[0] for donor in row)
        )
        for row in donors
    ]
