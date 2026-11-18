from datetime import datetime

from live_config import INDEX_FIELD, log_path, parse_arguments, run_build_dir

import lines

from build_model import BuildModel
from checkpoint_model import CheckpointModel
from conversion import Conversion
from export_config import selected_checkpoint
from glove import Glove
from postprocess import Postprocess
from run_log import RunLog
from window import WindowBuffer


def open_model(arguments):
    if arguments.run is not None:
        return BuildModel(run_build_dir(arguments.run))

    checkpoint = arguments.checkpoint or selected_checkpoint()[0]

    return CheckpointModel(checkpoint, arguments.norm_stats)


def main():
    arguments = parse_arguments()
    started = datetime.now()

    model = open_model(arguments)
    conversion = Conversion()

    if model.channel_names != conversion.channels:
        raise SystemExit(
            f"the model takes {model.channel_names}, but the gloves convert to "
            f"{conversion.channels}. The two disagree about the channel order."
        )

    labels = model.desc.labels
    buffer = WindowBuffer(model.desc.window, model.desc.channels)
    post = Postprocess(model.desc, model.channel_names)

    with Glove(arguments.port) as glove, RunLog(log_path(started)) as log:
        for line in lines.header(started, model, glove.port, buffer.window, buffer.stride):
            log.write(line, show=True)

        log.write("")
        log.write(lines.sample_head(conversion.channels))
        print("\nreading the gloves, Ctrl+C to stop\n", flush=True)

        samples = windows = events = 0
        first = None

        try:
            for reading in glove.readings():
                index = reading[INDEX_FIELD]
                first = index if first is None else first
                t = (index - first) / buffer.rate
                sample = conversion(reading)

                samples += 1
                log.write(lines.sample(samples, index, t, sample))

                got = buffer.push(sample, t)
                if got is None:
                    continue

                raw, stamp = got
                logits = model.logits(raw)

                windows += 1
                log.write(
                    lines.window(windows, samples - buffer.window + 1, samples,
                                 stamp, labels, post.scores(logits)),
                )

                for event in post.push(logits, raw, stamp):
                    events += 1
                    log.write(lines.event(event), show=True)
        except KeyboardInterrupt:
            print()

        log.write(lines.summary(samples, windows, events), show=True)

    print(f"saved     {log.path}")


if __name__ == "__main__":
    main()
