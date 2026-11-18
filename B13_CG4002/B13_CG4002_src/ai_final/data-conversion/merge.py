import pandas as pd

import convert_config as cc

from recording import raw_columns


def merged(paths):
    required = [cc.RAW_REP, cc.RAW_USER, cc.RAW_LABEL, *raw_columns()]
    tables = []

    for number, path in enumerate(paths):
        table = pd.read_csv(path)
        missing = [column for column in required if column not in table.columns]
        if missing:
            raise SystemExit(f"{path} is missing the collector's columns {missing}.")
        tables.append(table.assign(**{cc.RAW_FILE: number}))

    return pd.concat(tables, ignore_index=True)
