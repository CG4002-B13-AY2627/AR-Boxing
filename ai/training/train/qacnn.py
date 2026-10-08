import torch.nn as nn

from brevitas import nn as qnn
from brevitas.quant import (
    Int8ActPerTensorFixedPoint,
    Int8WeightPerTensorFixedPoint,
    Int32Bias,
    Uint8ActPerTensorFixedPoint,
)
from config import (
    NUM_CHANNELS,
    NUM_CLASSES,
    HIDDEN_UNITS,
    CONV1_FILTERS,
    CONV1_KERNEL,
    CONV2_FILTERS,
    CONV2_KERNEL,
    POOL_KERNEL,
    POOL_STRIDE,
    WEIGHT_BIT_WIDTH,
    ACT_BIT_WIDTH
)

# Input from the dataloader is (batch, window_size, channels) = (B, 32, 12).
# This shall be our quantization aware model. We are using Brevitas.


class QuantCNN(nn.Module):
    def __init__(
            self, 
            num_channels=NUM_CHANNELS, 
            num_classes=NUM_CLASSES, 
            hidden_units=HIDDEN_UNITS,
            weight_bit_width=WEIGHT_BIT_WIDTH,
            act_bit_width=ACT_BIT_WIDTH
    ):
        super().__init__() # Call the constructor of the parent

        # Quantizes the raw window so conv1 has a known input scale. 
        self.quant_input = qnn.QuantIdentity(
            act_quant=Int8ActPerTensorFixedPoint,
            bit_width=act_bit_width,
            return_quant_tensor=True,
        )

        # (B, 12, 32) -> (B, 32, 32)
        self.conv1 = qnn.QuantConv1d(
            num_channels,
            CONV1_FILTERS,
            kernel_size=CONV1_KERNEL,
            padding="same",
            bias=True,
            weight_quant=Int8WeightPerTensorFixedPoint,
            weight_bit_width=weight_bit_width,
            bias_quant=Int32Bias,
            return_quant_tensor=True,
        )
        self.relu1 = qnn.QuantReLU(
            act_quant=Uint8ActPerTensorFixedPoint,
            bit_width=act_bit_width,
            return_quant_tensor=True,
        )
        # (B, 32, 32) -> (B, 32, 16)
        # Max pooling is quant-invariant, so the plain layer passes the
        # QuantTensor through untouched. No quantized variant is needed.
        self.pool = nn.MaxPool1d(kernel_size=POOL_KERNEL, stride=POOL_STRIDE)

        # (B, 32, 16) -> (B, 64, 16)
        self.conv2 = qnn.QuantConv1d(
            CONV1_FILTERS,
            CONV2_FILTERS,
            kernel_size=CONV2_KERNEL,
            padding="same",
            bias=True,
            weight_quant=Int8WeightPerTensorFixedPoint,
            weight_bit_width=weight_bit_width,
            bias_quant=Int32Bias,
            return_quant_tensor=True,
        )
        self.relu2 = qnn.QuantReLU(
            act_quant=Uint8ActPerTensorFixedPoint,
            bit_width=act_bit_width,
            return_quant_tensor=True,
        )

        # (B, 64, 16) -> (B, 64, 1)
        # Brevitas registers no handler for adaptive_avg_pool1d, so this runs
        # on the plain tensor and quant_pool re-establishes the scale after.
        self.global_pool = nn.AdaptiveAvgPool1d(1)
        self.quant_pool = qnn.QuantIdentity(
            act_quant=Int8ActPerTensorFixedPoint,
            bit_width=act_bit_width,
            return_quant_tensor=True,
        )

        # (B, 64) -> (B, 32) -> (B, 11)
        self.fc1 = qnn.QuantLinear(
            CONV2_FILTERS,
            hidden_units,
            bias=True,
            weight_quant=Int8WeightPerTensorFixedPoint,
            weight_bit_width=weight_bit_width,
            bias_quant=Int32Bias,
            return_quant_tensor=True,
        )
        self.relu3 = qnn.QuantReLU(
            act_quant=Uint8ActPerTensorFixedPoint,
            bit_width=act_bit_width,
            return_quant_tensor=True,
        )

        # Logits leave as a plain tensor; CrossEntropyLoss cannot take a
        # QuantTensor, and argmax on the PS does not need the scale.
        self.fc2 = qnn.QuantLinear(
            hidden_units,
            num_classes,
            bias=True,
            weight_quant=Int8WeightPerTensorFixedPoint,
            weight_bit_width=weight_bit_width,
            bias_quant=Int32Bias,
            return_quant_tensor=False,
        )

    def forward(self, x):
        # x: (B, 32, 12) -> (B, 12, 32), Conv1d expects channels before time
        x = x.transpose(1, 2)

        x = self.quant_input(x)

        x = self.relu1(self.conv1(x))
        x = self.pool(x)
        x = self.relu2(self.conv2(x))

        # (B, 64, 1) -> (B, 64). .value drops to the plain tensor because
        # adaptive_avg_pool1d has no QuantTensor handler.
        x = self.global_pool(x.value).squeeze(-1)
        x = self.quant_pool(x)

        x = self.relu3(self.fc1(x))

        # (B, 11) logits
        return self.fc2(x)


def build_quant_model(device, weight_bit_width, act_bit_width):
    model = QuantCNN(
        weight_bit_width=weight_bit_width,
        act_bit_width=act_bit_width
    )
    model.to(device)

    return model


def transfer_weights(model, quant_model):
    """Copy the trained FP32 weights into QuantCNN as its float master copy.

    QAT then fine-tunes from a trained starting point rather than from scratch,
    which is what makes the accuracy difference attributable to the bit width
    instead of to two unrelated training runs.
    """
    pairs = [
        (model.conv1, quant_model.conv1),
        (model.conv2, quant_model.conv2),
        (model.fc1, quant_model.fc1),
        (model.fc2, quant_model.fc2),
    ]

    for source, target in pairs:
        # Shapes must agree exactly. If they do not, CNN and QuantCNN have
        # drifted apart and the comparison would no longer be like for like.
        target.weight.data.copy_(source.weight.data)
        target.bias.data.copy_(source.bias.data)

    return quant_model
