import numpy as np

from live_config import BAUD_RATE, SAMPLE_PRECISION, STARTED_FORMAT, TOP_K

COUNT_WIDTH = 8
VALUE_WIDTH = SAMPLE_PRECISION + 5


def header(started, model, port, window, stride):
    return [
        f"started   {started.strftime(STARTED_FORMAT)}",
        f"model     {model}",
        f"contract  {model.desc}",
        f"port      {port} at {BAUD_RATE} baud",
        f"windows   {window} samples at stride {stride}",
    ]


def sample_head(channels):
    return "  ".join([
        f"{'sample':>{COUNT_WIDTH}}",
        f"{'device':>{COUNT_WIDTH}}",
        f"{'t':>{COUNT_WIDTH}}",
        *(f"{channel:>{VALUE_WIDTH}}" for channel in channels),
    ])


def sample(n, index, t, values):
    return "  ".join([
        f"{n:>{COUNT_WIDTH}}",
        f"{index:>{COUNT_WIDTH}}",
        f"{t:>{COUNT_WIDTH}.3f}",
        *(f"{value:>{VALUE_WIDTH}.{SAMPLE_PRECISION}f}" for value in values),
    ])


def window(n, first, last, t, labels, scores):
    width = max(map(len, labels))
    top = np.argsort(scores)[::-1][:TOP_K]

    return "  ".join([
        f"window {n:>{COUNT_WIDTH}}",
        f"samples {first:>{COUNT_WIDTH}}-{last:<{COUNT_WIDTH}}",
        f"t {t:>{COUNT_WIDTH}.3f}s",
        *(f"{labels[k]:<{width}} {scores[k]:.2f}" for k in top),
    ])


def event(e):
    return f"event    {e}"


def summary(samples, windows, events):
    return f"stopped   {samples} samples, {windows} windows, {events} events"
