import convert_config as cc

from mirror import fit, flip, mirrored
from recording import recordings, side
from resample import resampled
from splice import spliced


def cells(reps):
    grouped = {}
    for rep in reps:
        grouped.setdefault((rep.participant, rep.label), []).append(rep)

    return grouped


def expanded(grouped, matrix, rng):
    return {
        (participant, label): reps + (
            [] if label in cc.REAL_ONLY
            else mirrored(grouped.get((participant, flip(label)), []), matrix)
            if side(label) or label in cc.SELF_MIRRORED
            else spliced(reps, max(cc.TARGET - len(reps), 0), rng) if label in cc.GLOVE_SPLICED
            else resampled(reps, max(cc.TARGET - len(reps), 0), rng)
        )
        for (participant, label), reps in grouped.items()
    }


def checked(grouped):
    wrong = {cell: len(reps) for cell, reps in grouped.items() if len(reps) < cc.TARGET}
    if wrong:
        raise SystemExit(f"Cells below {cc.TARGET}: {wrong}")

    return grouped


def assemble(table, rng):
    real = recordings(table)
    matrix = fit(real)
    grouped = checked(expanded(cells(real), matrix, rng))
    windows = [rep for _, reps in sorted(grouped.items()) for rep in reps]

    return matrix, [windows[index] for index in rng.permutation(len(windows))]
