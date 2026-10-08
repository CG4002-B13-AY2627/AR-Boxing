import hashlib
import math

import torch
import brevitas

import export_config

from export_config import train_config
from qacnn import QuantCNN

# Nothing configurable lives in this file. Which checkpoint is read, and the
# topology walked below — which weight layer sits between which activation
# quantizers, what the global pool spans, how wide the accumulators are — are
# in export_config.py, and the dimensions behind them are in train/config.py.


def file_sha256(path):
    """So a header can say which checkpoint it came from, not just which name."""
    # Here, we create a SHA-256 calculator. The final hash acts like a unique
    # fingerprint for the exact checkpoint file that we export.
    digest = hashlib.sha256()

    # We read the checkpoint in small blocks instead of loading the entire file
    # into memory at once. b"" means that we have reached the end of the file.
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(export_config.HASH_BLOCK_SIZE), b""):
            digest.update(block)

    # hexdigest() returns the fingerprint as a readable hexadecimal string.
    return digest.hexdigest()


def log2_exact(scale, what):
    """A power-of-two scale as its exponent, or a hard failure.

    The quantizers are configured with restrict_scaling_type = POWER_OF_TWO
    precisely so that every scale is a binary point position and costs nothing
    in hardware. If that ever stops holding, the export must stop here rather
    than emit a header whose arithmetic silently no longer matches the model.
    """
    # Here, we convert the Brevitas scale into a normal Python number before
    # calculating its base-2 logarithm.
    exponent = math.log2(float(scale))

    # We only accept whole-number exponents. For instance, 0.0625 = 2^{-4},
    # so its exponent is exactly -4. A non-integer exponent would mean that the
    # scale cannot be implemented using only a binary shift in hardware.
    if not float(exponent).is_integer():
        raise SystemExit(
            f"{what}: scale {float(scale)} is not a power of two "
            f"(log2 = {exponent}). Check the quantizer configuration in qacnn.py."
        )

    # We return an integer because the hardware shift amount must be a whole
    # number of bits.
    return int(exponent)


def clamp_range(bit_width, signed):
    """The saturation bounds the requantization clamps to."""
    # A signed W-bit integer ranges from -2^{W-1} to 2^{W-1} - 1. For
    # instance, a signed 6-bit integer ranges from -32 to 31.
    if signed:
        return -(2 ** (bit_width - 1)), 2 ** (bit_width - 1) - 1

    # An unsigned W-bit integer ranges from 0 to 2^W - 1. For instance, an
    # unsigned 6-bit integer ranges from 0 to 63.
    return 0, 2 ** bit_width - 1


def bits_for(value):
    """Signed two's complement bits needed to hold value."""
    # bit_length() counts the magnitude bits. We add one more bit for the sign.
    return int(value).bit_length() + 1


def load_model(path, width):
    """Rebuild the network at the checkpoint's width and load it for export."""

    # We recreate the CNN at the correct bit width, both weight and activation.
    # This first constructs an empty network with an architecture from my qacnn.py
    model = QuantCNN(weight_bit_width=width, act_bit_width=width)

    # Then, we load the trained weights.
    model.load_state_dict(torch.load(path, map_location=export_config.LOAD_DEVICE))

    # This tells Pytorch and Brevitas that the model is used for inference.
    model.eval()

    # quant_bias() needs the input scale, which the proxy only has after it has
    # seen a forward pass. Without this it raises "Input scale required".
    for name, _, _, _ in export_config.WEIGHT_LAYERS:
        getattr(model, name).bias_quant.cache_inference_quant_bias = True

    # Run one dummy input.
    with torch.no_grad():
        model(torch.zeros(1, train_config.WINDOW_SIZE, train_config.NUM_CHANNELS))

    # Returns the ready model.
    return model


def activation_spec(model, name):
    """Scale, width and saturation bounds of one activation quantizer."""
    # getattr(model, name) lets us access a layer using a string. For instance,
    # when name is "relu1", this is equivalent to model.relu1.act_quant.
    quantizer = getattr(model, name).act_quant

    # We read the settings learned or configured by the Brevitas quantizer.
    bit_width = int(quantizer.bit_width())
    signed = bool(quantizer.is_signed)

    # We then calculate the smallest and largest integers that this activation
    # is allowed to contain.
    low, high = clamp_range(bit_width, signed)

    # Here, log2_scale is the log_{2} of the scale. For instance,
    # if our scale is 2^{-4}, then we get -4 as the log2_scale.
    return {
        "log2_scale": log2_exact(quantizer.scale(), f"{name} activation"),
        "bit_width": bit_width,
        "signed": signed,
        "clamp_low": low,
        "clamp_high": high,
    }


def weight_spec(model, name, width):
    """Integer weights and bias of one layer, with their scales."""
    # As with activation_spec(), getattr() selects the requested layer by name.
    # For instance, name = "conv1" gives us model.conv1.
    module = getattr(model, name)

    # Ask brevitas for the quantized parameters.
    # This holds both the quantized numbers and information about their scales.
    quant_weight = module.quant_weight()
    quant_bias = module.quant_bias()

    # We then get the integer forms used by the hardware implementation. These
    # are different from the floating-point values displayed during training.
    weight = quant_weight.int()
    bias = quant_bias.int()

    # We calculate the valid range for a signed integer at the selected width.
    low, high = clamp_range(width, signed=True)

    # Every weight must fit inside that range. If even one weight does not fit,
    # we stop instead of silently exporting a value that hardware cannot store.
    if int(weight.min()) < low or int(weight.max()) > high:
        raise SystemExit(
            f"{name}: weights span [{int(weight.min())}, {int(weight.max())}], "
            f"which does not fit {width} signed bits."
        )

    # tolist() converts PyTorch tensors into plain Python lists. This makes the
    # extracted description easy to write into JSON or C++ header files later.
    return {
        "weight": weight.tolist(),
        "weight_shape": list(weight.shape),
        "weight_log2_scale": log2_exact(quant_weight.scale, f"{name} weight"),
        "bias": bias.tolist(),
        "bias_log2_scale": log2_exact(quant_bias.scale, f"{name} bias"),
        "bias_bit_width": int(quant_bias.bit_width),
    }


def requantization(layer, activations, spec, width):
    """The shift, clamp and accumulator width for one weight layer.

    An accumulator holds the dot product at the product scale, 2^(e_in + e_w).
    Bringing it to the output scale 2^e_out is a division by 2^(e_out - e_in -
    e_w), and because every scale is a power of two that division is a right
    shift by a compile-time constant. The shift is non-negative because the
    output scale is always coarser than the accumulator's.
    """
    # Each row has the form:
    # (layer name, layer kind, input activation, output activation).
    # For instance, conv1 receives quant_input and produces relu1.
    name, kind, input_name, output_name = layer

    # e_in and e_w are base-2 scale exponents. For instance, if the input scale
    # is 2^{-4} and the weight scale is 2^{-7}, they are -4 and -7.
    e_in = activations[input_name]["log2_scale"]
    e_w = spec["weight_log2_scale"]

    # The bias is quantized at exactly the accumulator scale, which is what
    # lets it be added as a plain integer with no alignment.
    if spec["bias_log2_scale"] != e_in + e_w:
        raise SystemExit(
            f"{name}: bias scale 2^{spec['bias_log2_scale']} does not match the "
            f"accumulator scale 2^{e_in + e_w}."
        )

    # Fan-in of one output, chosen by the layer's kind in WEIGHT_LAYERS: a conv
    # sums in_channels x kernel products, a linear sums in_features. Both
    # counts come off the weight tensor, so the table states no sizes.
    # Here, terms is the number of multiplications summed to produce one output.
    # A convolution uses input_channels x kernel_size terms, while a linear
    # layer uses one term for every input feature.
    if kind == "conv":
        terms = spec["weight_shape"][1] * spec["weight_shape"][2]
    else:
        terms = spec["weight_shape"][1]

    # Two operands of `width` bits give a product of 2 * width bits, and
    # summing `terms` of them adds ceil(log2(terms)). The bias is a wider
    # integer than that in its own right, so take whichever needs more.
    # We calculate the width required by both the dot product and the bias, and
    # choose the larger value so that neither one can overflow the accumulator.
    needed = max(
        2 * width + math.ceil(math.log2(terms)),
        bits_for(max(abs(value) for value in spec["bias"])),
    )

    # No ceiling check here. One layer's requirement is not the width: acc_t is
    # a single type shared by the whole network, so that decision belongs where
    # every demand is visible at once, which is accumulator_bits() below.

    # Multiplying values with scales 2^{e_in} and 2^{e_w} gives the accumulator
    # scale 2^{e_in + e_w}. For instance, 2^{-4} x 2^{-7} = 2^{-11}.
    result = {
        "input_activation": input_name,
        "output_activation": output_name,
        "terms": terms,
        "accumulator_log2_scale": e_in + e_w,
        "accumulator_bits_required": needed,
    }

    # A row with no output activation — fc2 — is the exception: nothing
    # requantizes the logits, so they leave the core as raw accumulators and
    # the PS takes an argmax over them.
    if output_name is None:
        # fc2 has no output quantizer. It returns raw class-score accumulators,
        # so there is no output shift or clamp to record for this layer.
        result["shift"] = None
        result["clamp_low"] = None
        result["clamp_high"] = None
    else:
        # All other weighted layers must convert the accumulator scale into the
        # next activation's scale and clamp the result to that activation's
        # valid integer range.
        output = activations[output_name]

        # For instance, converting from 2^{-11} to 2^{-5} requires a right
        # shift of -5 - (-11) = 6 bits.
        result["shift"] = output["log2_scale"] - (e_in + e_w)
        result["clamp_low"] = output["clamp_low"]
        result["clamp_high"] = output["clamp_high"]

        # A negative value would require a left shift, which this export format
        # does not allow. We therefore stop and report the incompatible layer.
        if result["shift"] < 0:
            raise SystemExit(f"{name}: negative shift {result['shift']}.")

    # This smaller dictionary is added to the weight information for the layer.
    return result


def pooling(activations):
    """The global average pool, which is a sum and one rounded shift.

    Brevitas averages in float and the pool's output quantizer rounds the
    result once. Matching that means accumulating the POOL_SIZE integers and
    rounding exactly once at the end: dividing by POOL_SIZE first and then
    requantizing rounds twice and drifts a least significant bit off the model
    on some windows.
    """
    # These names describe the activation immediately before and after the
    # global average pool. In this network, they are relu2 and quant_pool.
    input_name = export_config.POOL_INPUT_ACTIVATION
    output_name = export_config.POOL_OUTPUT_ACTIVATION

    # After the stride-2 max pool, the original 32 time positions become 16.
    # Therefore, the global average pool combines 16 integer values per channel.
    size = export_config.POOL_SIZE

    # Averaging over `size` is a division by `size`, and the only division this
    # datapath has is a right shift, so `size` has to be a power of two. This
    # is the architecture's constraint on WINDOW_SIZE, and it was until now
    # written down nowhere: int(math.log2(24)) is 4, so a 24-step pool would
    # have emitted a shift that divides by 16 and left every pooled value half
    # again too large. log2_exact() is not reused for it because its advice
    # points at qacnn.py, and a window length is not a quantizer's fault.
    if size < 1 or size & (size - 1):
        raise SystemExit(
            f"the global pool spans {size} timesteps, which is not a power of "
            f"two, so averaging it cannot be a right shift. WINDOW_SIZE and the "
            f"max pool have to leave a power-of-two number of steps between "
            f"them; {size} came from WINDOW_SIZE {train_config.WINDOW_SIZE}, "
            f"kernel {export_config.MAXPOOL_KERNEL}, stride "
            f"{export_config.MAXPOOL_STRIDE}."
        )

    # We need both scales so that the pooled sum can be converted from the
    # relu2 scale into the quant_pool scale.
    e_in = activations[input_name]["log2_scale"]
    output = activations[output_name]

    # The pool sums `size` activations into acc_t before it shifts, and nothing
    # else sizes that sum: the pool carries no weights, so it is not a
    # WEIGHT_LAYERS row and requantization() never sees it. Worst case is every
    # one of them sitting at whichever clamp bound is further from zero.
    peak = size * max(
        abs(activations[input_name]["clamp_low"]),
        abs(activations[input_name]["clamp_high"]),
    )

    # Since size is 16 = 2^4, averaging contributes a right shift of 4 bits.
    # The scale conversion is added to this to form one final rounded shift.
    return {
        "size": size,
        "input_activation": input_name,
        "output_activation": output_name,
        "shift": int(math.log2(size)) + (output["log2_scale"] - e_in),
        "clamp_low": output["clamp_low"],
        "clamp_high": output["clamp_high"],
        "accumulator_bits_required": bits_for(peak),
    }


def accumulator_bits(layers, pool):
    """The one width acc_t has to be, derived from what the network needs.

    acc_t is a single type, shared by every dot product and by the pool's sum,
    so it is sized for the widest of them rather than per layer. Each demand is
    already computed where that part of the network is described; this takes
    the largest and holds it against the ceiling.

    Deriving it rather than declaring it means the width tracks the
    architecture: widening a layer, adding a class or moving the quantization
    width moves the requirement, and the header follows without anyone
    remembering to. The cost, stated because section 5.6 quotes this number, is
    that it is now partly a function of the trained bias magnitudes, so two
    checkpoints of one architecture can differ by a bit. Which one a build got
    is in meta.accumulator_width and in the provenance of every header.
    """
    demands = [
        (layer["accumulator_bits_required"], layer["name"]) for layer in layers
    ]
    demands.append((pool["accumulator_bits_required"], "the global pool"))

    needed, where = max(demands)

    if needed > export_config.ACCUMULATOR_WIDTH_MAX:
        raise SystemExit(
            f"{where} needs a {needed}-bit accumulator, past the "
            f"{export_config.ACCUMULATOR_WIDTH_MAX}-bit ceiling set by "
            f"ACCUMULATOR_WIDTH_MAX in export_config.py. Raise it deliberately, "
            f"or find out why a layer grew this far."
        )

    return needed


def extract(path=None, width=None):
    """The whole integer description of one checkpoint, ready to be emitted.

    Called with nothing it exports whatever the training sweep selected, which
    is the normal case. Both arguments stay open so a caller sweeping widths
    for the utilisation table can point at one checkpoint of its own; the width
    still comes off the filename unless it is given explicitly.
    """
    # If no path is supplied, we ask export_config.py for the checkpoint chosen
    # by the training sweep and the bit width encoded in its filename.
    if path is None:
        path, width = export_config.selected_checkpoint()

    # If a caller supplies a checkpoint but no width, we read the width from a
    # filename such as qacnn_w6.pt, where w6 means a width of 6 bits.
    elif width is None:
        width = export_config.checkpoint_width(path)

    # Here, we rebuild QuantCNN at the selected width, load the trained state,
    # switch it to inference mode, and run the dummy input needed by Brevitas.
    model = load_model(path, width)

    # This dictionary comprehension calls activation_spec() once for every
    # activation listed in export_config.ACTIVATIONS. The dictionary key is the
    # activation's name and the value is its scale, width, and clamp information.
    activations = {
        name: activation_spec(model, name)
        for name in export_config.ACTIVATIONS
    }

    # We will add one extracted dictionary for conv1, conv2, fc1, and fc2.
    layers = []

    # WEIGHT_LAYERS states how each weighted layer connects two activations.
    # We walk through those rows in the same order as the network.
    for layer in export_config.WEIGHT_LAYERS:
        # We need the name and kind here. The two underscores mean that the
        # input and output activation names are intentionally unused on this line.
        name, kind, _, _ = layer

        # First, we extract this layer's integer weights, bias, tensor shape,
        # scales, and bias width.
        spec = weight_spec(model, name, width)

        # We identify the layer in its dictionary, then merge in the shift,
        # clamp, fan-in, and accumulator information from requantization().
        spec["name"] = name
        spec["kind"] = kind
        spec.update(requantization(layer, activations, spec, width))

        # The completed specification becomes one entry in the layers list.
        layers.append(spec)

    # Bound before the description is assembled, because the accumulator width
    # is derived from this and from the layers above together.
    global_pool = pooling(activations)

    # extract() only returns this Python dictionary. It does not write a file.
    # Other export code can later turn this description into JSON or C++ headers.
    return {
        "meta": {
            # Metadata lets us trace an exported description back to the exact
            # checkpoint, library versions, input shape, and class ordering.
            "checkpoint": path.name,
            "sha256": file_sha256(path),
            "bit_width": width,
            # Derived from the layers and the pool, never read from a config.
            # Every consumer of acc_t takes the width from here.
            "accumulator_width": accumulator_bits(layers, global_pool),
            "torch": torch.__version__,
            "brevitas": brevitas.__version__,
            "window_size": train_config.WINDOW_SIZE,
            "num_channels": train_config.NUM_CHANNELS,
            "num_classes": train_config.NUM_CLASSES,
            "labels": [
                train_config.ID_TO_LABEL[index]
                for index in range(train_config.NUM_CLASSES)
            ],
        },
        "activations": activations,
        "layers": layers,
        # No scales to derive: max is quant invariant, so the max pool passes
        # its input's scale straight through and only its geometry is needed.
        "maxpool": {
            "kernel": export_config.MAXPOOL_KERNEL,
            "stride": export_config.MAXPOOL_STRIDE,
            "output_size": export_config.MAXPOOL_OUTPUT,
        },
        "global_pool": global_pool,
    }
