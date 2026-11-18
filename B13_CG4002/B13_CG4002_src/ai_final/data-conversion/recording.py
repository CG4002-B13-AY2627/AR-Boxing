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


def recordings(table):
    runs = rep_ids(table)
    short = (runs.value_counts() != cc.WINDOW).sum()
    if short:
        raise SystemExit(f"{short} reps are not {cc.WINDOW} samples long.")

    columns = raw_columns()

    return [
        Rep(
            int(run[cc.RAW_USER].iat[0]),
            cc.RAW_ID_TO_LABEL[int(run[cc.RAW_LABEL].iat[0])],
            cc.REAL,
            int(run[cc.RAW_USER].iat[0]),
            (int(run.index[0]), int(run.index[-1])),
            run[columns].to_numpy(float)
        )
        for _, run in table.groupby(runs)
    ]
