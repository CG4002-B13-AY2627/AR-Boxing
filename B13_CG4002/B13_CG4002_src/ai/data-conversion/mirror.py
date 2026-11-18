from itertools import permutations, product

import numpy as np

import convert_config as cc

from recording import Rep, channels, nodes, other, quantise, side


def flip(label):
    node, _, action = label.partition("_")

    return f"{other(node)}_{action}" if side(label) else label


def candidates():
    for order in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            matrix = np.zeros((3, 3))
            matrix[range(3), order] = signs
            if np.linalg.det(matrix) < 0:
                yield matrix


def reflect(signal, matrix):
    left, right = nodes()
    out = np.empty_like(signal)

    for kind, linear in ((cc.ACCEL, matrix), (cc.GYRO, -matrix)):
        out[:, channels(right, kind)] = signal[:, channels(left, kind)] @ linear.T
        out[:, channels(left, kind)] = signal[:, channels(right, kind)] @ linear

    return quantise(out)


def template(reps):
    return np.mean([rep.signal for rep in reps], axis=0)


def pairs(reps):
    grouped = {}
    for rep in reps:
        grouped.setdefault((rep.participant, rep.label), []).append(rep)

    left = nodes()[0]

    return [
        (template(grouped[(participant, label)]), template(grouped[(participant, flip(label))]))
        for participant, label in grouped
        if side(label) == left and (participant, flip(label)) in grouped
    ]


def fit(reps):
    matched = pairs(reps)
    if not matched:
        return None

    return min(
        candidates(),
        key=lambda matrix: sum(np.mean((reflect(a, matrix) - b) ** 2) for a, b in matched)
    )


def mirrored(reps, matrix):
    if matrix is None:
        return []

    return [
        Rep(rep.participant, flip(rep.label), cc.MIRRORED, rep.donor, rep.rows, reflect(rep.signal, matrix))
        for rep in reps
    ]
