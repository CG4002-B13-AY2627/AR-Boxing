from collections import namedtuple

import numpy as np

import convert_config as cc

Rep = namedtuple(
    "Rep", ["participant", "label", "source", "donor", "rows", "signal", "parts"], defaults=(None,)
)


def split(column):
    node, _, axis = column.partition("_")
    return node, axis


def nodes():
    return list(dict.fromkeys(split(column)[0] for column in cc.FEATURE_COLUMNS))


def sensor(column):
    return split(column)[1][0]


def channels(node, kind):
    return [
        index for index, column in enumerate(cc.FEATURE_COLUMNS)
        if split(column)[0] == node and sensor(column) == kind
    ]


def side(label):
    node = label.partition("_")[0]
    return node if node in nodes() else None


def other(node):
    return next(candidate for candidate in nodes() if candidate != node)


def raw_columns():
    return [
        f"{cc.RAW_NODE[node]}_{axis}"
        for node, axis in map(split, cc.FEATURE_COLUMNS)
    ]


def units():
    return np.array([
        cc.GRAVITY / cc.ACCEL_LSB_PER_G if sensor(column) == cc.ACCEL
        else np.radians(1) / cc.GYRO_LSB_PER_DPS
        for column in cc.FEATURE_COLUMNS
    ])


def quantise(signal):
    return np.clip(np.rint(signal), cc.RAW_MIN, cc.RAW_MAX)


def rep_ids(table):
    key = table[[cc.RAW_FILE, cc.RAW_USER, cc.RAW_LABEL, cc.RAW_REP]]
    return key.ne(key.shift()).any(axis=1).cumsum()


def problem(run, label):
    if len(run) != cc.WINDOW:
        return f"not {cc.WINDOW} samples long"
    if label not in cc.LABEL_TO_ID:
        return f"labelled {label or int(run[cc.RAW_LABEL].iat[0])}, which the model has no class for"
    return None


def recordings(table):
    columns = raw_columns()
    reps = []
    skipped = {}

    for _, run in table.groupby(rep_ids(table)):
        label = cc.RAW_ID_TO_LABEL.get(int(run[cc.RAW_LABEL].iat[0]))
        reason = problem(run, label)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue

        reps.append(Rep(
            int(run[cc.RAW_USER].iat[0]),
            label,
            cc.REAL,
            int(run[cc.RAW_USER].iat[0]),
            (int(run.index[0]), int(run.index[-1])),
            run[columns].to_numpy(float)
        ))

    return reps, skipped
