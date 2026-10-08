import numpy as np
import pandas as pd

from scipy.signal import decimate, find_peaks

import zenodo_config as zc


def samples(seconds):
    return int(round(seconds * zc.TARGET_RATE_HZ))


def hand(label):
    return label.split("_")[0]


def other(side):
    return "r" if side == "l" else "l"


def load(name):
    frame = pd.read_csv(zc.SOURCE_DIR / f"{name}.csv", header=None)
    raw = frame.apply(pd.to_numeric, errors="coerce").dropna().to_numpy(float)

    return decimate(
        raw, zc.SOURCE_RATE_HZ // zc.TARGET_RATE_HZ,
        ftype="fir", zero_phase=True, axis=0
    )


def convert(x):
    return np.hstack([x[:, 3:] * zc.GRAVITY, np.radians(x[:, :3])])


def spike(x):
    return np.abs(np.linalg.norm(x[:, 3:], axis=1) - 1)


def rotation(x):
    return np.linalg.norm(x[:, :3], axis=1)


def punches(x):
    height = spike(x)
    turn = rotation(x)
    reach = samples(zc.ROTATION_REACH_S)

    peaks, _ = find_peaks(
        height,
        prominence=zc.PEAK_PROMINENCE_G,
        distance=samples(zc.PEAK_SPACING_S)
    )
    peaks = peaks[np.array([
        turn[max(0, peak - reach):peak + reach + 1].max() >= zc.ROTATION_MIN_DPS
        for peak in peaks
    ], dtype=bool)]
    peaks = peaks[height[peaks] >= zc.SPIKE_FRACTION * np.median(height[peaks])]

    close = np.diff(peaks) <= samples(zc.NEIGHBOUR_S)

    return peaks[np.r_[close, False] | np.r_[False, close]]


def guards(x, peaks):
    quiet = (spike(x) <= zc.GUARD_TOLERANCE_G) & (rotation(x) < zc.GUARD_ROTATION_MAX_DPS)
    clear = samples(zc.GUARD_CLEAR_S)

    for peak in peaks:
        quiet[max(0, peak - clear):peak + clear + 1] = False

    return [
        start for start in range(0, len(x) - zc.WINDOW + 1, zc.WINDOW)
        if quiet[start:start + zc.WINDOW].all()
    ]


def offsets():
    central = samples(zc.CENTRAL_S)
    low = (zc.WINDOW - central) // 2

    return low, low + central


def owner(source, start):
    cuts = [samples(cut) for cut in source.cuts_s]
    first = np.searchsorted(cuts, start, side="right")
    last = np.searchsorted(cuts, start + zc.WINDOW - 1, side="right")

    return source.participants[first] if first == last else None


def recordings(rng):
    punched = []
    pool = {}
    low, high = offsets()

    for name, source in zc.SOURCES.items():
        x = load(name)
        side = hand(source.label)
        peaks = punches(x)

        for peak in peaks:
            start = int(peak - rng.integers(low, high))
            if start < 0 or start + zc.WINDOW > len(x):
                continue

            participant = owner(source, start)
            if participant is not None:
                punched.append((
                    source.label, side, participant,
                    convert(x[start:start + zc.WINDOW])
                ))

        for start in guards(x, peaks):
            participant = owner(source, start)
            if participant is not None:
                pool.setdefault((side, participant), []).append(
                    convert(x[start:start + zc.WINDOW])
                )

    return punched, pool


def draw(pool, side, participant, rng):
    windows = pool.get((side, participant))
    if not windows:
        raise SystemExit(f"No guard windows for hand {side}, participant {participant}.")

    return windows[rng.integers(len(windows))]


def assemble(rng):
    punched, pool = recordings(rng)
    windows = []

    for label, side, participant, signal in punched:
        guard = draw(pool, other(side), participant, rng)
        pair = {side: signal, other(side): guard}
        windows.append((participant, label, pair["l"], pair["r"]))

    participants = sorted({participant for _, _, participant, _ in punched})
    classes = {label for label, _, _, _ in punched}
    idle = round(len(punched) / len(classes))

    for number in range(idle):
        participant = participants[number % len(participants)]
        windows.append((
            participant, zc.IDLE_LABEL,
            draw(pool, "l", participant, rng),
            draw(pool, "r", participant, rng)
        ))

    return [windows[index] for index in rng.permutation(len(windows))]


def frame(windows):
    rows = len(windows) * zc.WINDOW
    features = np.concatenate([np.hstack([left, right]) for _, _, left, right in windows])
    labels = np.full(rows, None, dtype=object)
    labels[zc.WINDOW - 1::zc.WINDOW] = [label for _, label, _, _ in windows]

    table = pd.DataFrame(features.round(zc.PRECISION), columns=zc.FEATURE_COLUMNS)
    table.insert(0, zc.PARTICIPANT_COLUMN, np.repeat([p for p, _, _, _ in windows], zc.WINDOW))
    table.insert(0, "index", np.arange(rows))
    table[zc.LABEL_COLUMN] = labels

    return table
