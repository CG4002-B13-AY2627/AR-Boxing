import hashlib

import numpy as np

from u96_config import TABLE_DIGEST_CHARS


def digest(data):
    return hashlib.sha256(data).hexdigest()[:TABLE_DIGEST_CHARS]


def render(source, segment, window, stride, labels, logits):
    segment = np.ascontiguousarray(segment, dtype=np.float32)
    logits = np.asarray(logits, dtype=np.int64).reshape(-1, len(labels))

    spans = [f"{n * stride}:{n * stride + window}" for n in range(len(logits))]
    predicted = [labels[k] for k in logits.argmax(axis=1)]

    span_width = max(len("samples"), *map(len, spans))
    widths = [
        max(len(label), *(len(str(v)) for v in logits[:, j]))
        for j, label in enumerate(labels)
    ]

    head = "  ".join([
        f"{'window':>6}",
        f"{'samples':<{span_width}}",
        *(f"{label:>{w}}" for label, w in zip(labels, widths)),
        "predicted",
    ])
    rows = [
        "  ".join([
            f"{n + 1:>6}",
            f"{span:<{span_width}}",
            *(f"{v:>{w}}" for v, w in zip(row, widths)),
            label,
        ])
        for n, (span, row, label) in enumerate(zip(spans, logits.tolist(), predicted))
    ]
    rule = "-" * max(len(line) for line in [head, *rows])
    body = "\n".join(rows)

    return "\n".join([
        f"source    {source}",
        f"segment   {len(segment)} samples x {segment.shape[1]} channels, "
        f"sha256 {digest(segment.tobytes())}",
        f"windows   {len(logits)} of {window} samples at stride {stride}",
        "",
        head,
        rule,
        body,
        rule,
        f"table     sha256 {digest(body.encode())}",
    ]) + "\n"
