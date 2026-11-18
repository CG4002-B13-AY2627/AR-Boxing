import numpy as np
import pandas as pd

import convert_config as cc

from recording import units


def frame(windows):
    rows = len(windows) * cc.WINDOW
    features = np.concatenate([rep.signal for rep in windows]) * units()
    labels = np.full(rows, None, dtype=object)
    labels[cc.WINDOW - 1::cc.WINDOW] = [rep.label for rep in windows]

    table = pd.DataFrame(features.round(cc.PRECISION), columns=cc.FEATURE_COLUMNS)
    table.insert(0, cc.PARTICIPANT_COLUMN, np.repeat([rep.participant for rep in windows], cc.WINDOW))
    table.insert(0, "index", np.arange(rows))
    table[cc.LABEL_COLUMN] = labels

    return table


def provenance(windows):
    return pd.DataFrame({
        "window": np.arange(len(windows)),
        cc.PARTICIPANT_COLUMN: [rep.participant for rep in windows],
        cc.LABEL_COLUMN: [rep.label for rep in windows],
        "source": [rep.source for rep in windows],
        "donor": [rep.donor for rep in windows],
        "raw_first_row": pd.array([rep.rows[0] for rep in windows], dtype="Int64"),
        "raw_last_row": pd.array([rep.rows[1] for rep in windows], dtype="Int64"),
        "channel_first_rows": [" ".join(map(str, rep.parts)) if rep.parts else None for rep in windows],
    })
