import json

from pathlib import Path

import torch

from description import Description
from export_config import checkpoint_width
from extract import extract, load_model
from golden import integer_logits


class CheckpointModel:
    def __init__(self, checkpoint, norm_stats):
        self.path = Path(checkpoint)
        self.stats_path = Path(norm_stats)

        for path in (self.path, self.stats_path):
            if not path.is_file():
                raise SystemExit(f"{path}: missing.")

        width = checkpoint_width(self.path)
        self.description = extract(self.path, width)
        self.desc = Description(self.path, self.description)
        self.model = load_model(self.path, width)

        stats = json.loads(self.stats_path.read_text())
        self.channel_names = list(stats["channels"])
        self.mean = torch.tensor(stats["mean"], dtype=torch.float32)
        self.std = torch.tensor(stats["std"], dtype=torch.float32)

        if len(self.channel_names) != self.desc.channels:
            raise SystemExit(
                f"{self.stats_path.name}: {len(self.channel_names)} channels, but "
                f"{self.path.name} takes {self.desc.channels}."
            )

    def __str__(self):
        return f"brevitas  {self.path}  stats {self.stats_path}"

    def logits(self, raw):
        x = (torch.from_numpy(raw) - self.mean) / self.std

        with torch.no_grad():
            out = self.model(x.unsqueeze(0)).numpy()[0]

        return integer_logits(self.description, out)
