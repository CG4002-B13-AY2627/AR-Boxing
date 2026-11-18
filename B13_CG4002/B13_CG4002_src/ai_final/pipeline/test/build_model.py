import json

import numpy as np

from check_config import DEFAULT_ROUNDING
from int_model import IntegerModel
from preprocess import Preprocess


class BuildModel:
    def __init__(self, build_dir):
        self.pre = Preprocess(build_dir)
        self.desc = self.pre.desc
        self.channel_names = self.pre.channel_names
        self.model = IntegerModel(json.loads(self.desc.path.read_text()), DEFAULT_ROUNDING)

    def __str__(self):
        return f"integers  {self.desc.path}"

    def logits(self, raw):
        logits, _, _ = self.model.forward(self.pre.window(raw).astype(np.int64))

        return logits
