import json

import export_config
import emit
import golden

from extract import extract

def description_path(width):
    return export_config.BUILD_DIR / export_config.DESCRIPTION_NAME.format(width)

def write_description(description):
    width = description["meta"]["bit_width"]
    path = description_path(width)

    export_config.BUILD_DIR.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(description, f, indent=2)
        f.write("\n")

    return path

def summarise(description):
    meta = description["meta"]

    print(f"checkpoint  {meta['checkpoint']}")
    print(f"sha256      {meta['sha256']}")
    print(f"bit width   {meta['bit_width']}")
    print(
        f"input       {meta['window_size']} x {meta['num_channels']}"
        f" -> {meta['num_classes']} classes"
    )
    # Worth printing because it is derived: it can move between two checkpoints
    # of the same architecture, and section 5.6 quotes it.
    print(f"accumulator {meta['accumulator_width']} bits (acc_t)")
    print()
    print(f"{'layer':<8}{'kind':<8}{'shape':<20}{'shift':<8}{'clamp':<14}{'acc'}")

    for layer in description["layers"]:
        shape = "x".join(str(dimension) for dimension in layer["weight_shape"])

        # fc2 requantizes to nothing: it emits raw accumulators for the PS to
        # take an argmax over, so it has no shift and no clamp to show.
        if layer["shift"] is None:
            shift = "-"
            clamp = "raw logits"
        else:
            shift = f">>{layer['shift']}"
            clamp = f"[{layer['clamp_low']}, {layer['clamp_high']}]"

        print(
            f"{layer['name']:<8}{layer['kind']:<8}{shape:<20}{shift:<8}"
            f"{clamp:<14}{layer['accumulator_bits_required']}"
        )

    pool = description["global_pool"]

    print()
    print(
        f"pool        {pool['size']} -> 1, >>{pool['shift']}, "
        f"clamp [{pool['clamp_low']}, {pool['clamp_high']}], "
        f"acc {pool['accumulator_bits_required']}"
    )


def main():
    description = extract()

    path = write_description(description)

    # Write the emit. Render the description as HLS-compatible C++ constants.
    written = emit.emit(
        description=description,
        out_dir=export_config.OUT_DIR
    )

    # The vectors the testbench checks nn_infer() against. Written from the
    # same description, in the same run, so they cannot belong to a different
    # checkpoint than the weights they will be compared against.
    vectors = golden.golden(
        description=description,
        out_dir=export_config.OUT_DIR
    )

    summarise(description)

    print()
    for output in [path] + written + vectors:
        print(f"written     {output}")


if __name__ == "__main__":
    main()
