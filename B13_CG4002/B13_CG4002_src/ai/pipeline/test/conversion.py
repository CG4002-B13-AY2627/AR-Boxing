import numpy as np

from live_config import DATASET_CONFIG_NAME, DATASET_SCRIPT_DIR, train_config


class Conversion:
    def __init__(self):
        if not (DATASET_SCRIPT_DIR / DATASET_CONFIG_NAME).is_file():
            raise SystemExit(
                f"{train_config.CSV_NAME} was not recorded with the gloves: "
                f"{DATASET_SCRIPT_DIR} has no {DATASET_CONFIG_NAME}, so there is no "
                "conversion from glove counts to the units the model trained on."
            )

        import recording

        self.channels = list(train_config.FEATURE_COLUMNS)
        self.fields = recording.raw_columns()
        self.scale = recording.units()

    def __call__(self, reading):
        return np.array([reading[field] for field in self.fields], dtype=np.float64) * self.scale
