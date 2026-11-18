import convert_config as cc

from mirror import fit, flip, mirrored
from recording import recordings, side
from resample import resampled
from splice import spliced


def cells(reps):
    grouped = {}
    for rep in reps:
        grouped.setdefault((rep.participant, rep.label), []).append(rep)

    for participant, label in list(grouped):
        if side(label) and label not in cc.REAL_ONLY:
            grouped.setdefault((participant, flip(label)), [])

    return grouped


def added(grouped, participant, label, reps, matrix, target, rng):
    if label in cc.REAL_ONLY:
        return []
    if side(label) or label in cc.SELF_MIRRORED:
        return mirrored(grouped.get((participant, flip(label)), []), matrix)
    if label in cc.GLOVE_SPLICED:
        return spliced(reps, max(target - len(reps), 0), rng)
    return resampled(reps, max(target - len(reps), 0), rng)


def expanded(grouped, matrix, target, rng):
    return {
        (participant, label): reps + added(grouped, participant, label, reps, matrix, target, rng)
        for (participant, label), reps in grouped.items()
    }


def recorded(windows):
    return [window for window in windows if window.source in (cc.REAL, cc.MIRRORED)]


def topped_up(grouped, target, rng):
    return {
        cell: windows + resampled(recorded(windows), max(target - len(windows), 0), rng)
        for cell, windows in grouped.items()
        if windows
    }


def missing(grouped, reps):
    participants = sorted({rep.participant for rep in reps})
    return [
        (participant, label)
        for participant in participants
        for label in cc.LABEL_TO_ID
        if (participant, label) not in grouped
    ]


def assemble(table, rng, target=cc.TARGET):
    real, skipped = recordings(table)
    matrix = fit(real)
    grouped = topped_up(expanded(cells(real), matrix, target, rng), target, rng)
    windows = [rep for _, reps in sorted(grouped.items()) for rep in reps]

    return matrix, [windows[index] for index in rng.permutation(len(windows))], skipped, missing(grouped, real)
