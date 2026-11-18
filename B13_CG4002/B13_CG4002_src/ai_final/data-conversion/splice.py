import numpy as np

import convert_config as cc

from recording import Rep, channels, nodes


def glove_columns(node):
    return channels(node, cc.ACCEL) + channels(node, cc.GYRO)


def spliced(reps, count, rng):
    pairs = len(reps) * (len(reps) - 1)
    count = min(count, pairs)
    if not count:
        return []

    left, right = nodes()

    first = reps[0]
    out = []
    for index in rng.choice(pairs, count, replace=False):
        a, offset = divmod(int(index), len(reps) - 1)
        b = offset + (offset >= a)

        signal = reps[b].signal.copy()
        signal[:, glove_columns(left)] = reps[a].signal[:, glove_columns(left)]

        donors = np.full(signal.shape[1], b)
        donors[glove_columns(left)] = a

        out.append(Rep(
            first.participant, first.label, cc.SPLICED, first.participant, (None, None),
            signal, tuple(reps[donor].rows[0] for donor in donors)
        ))

    return out
