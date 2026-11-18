import torch.nn as nn

from torchsummary import summary

from config import (
    WINDOW_SIZE,
    NUM_CHANNELS,
    NUM_CLASSES,
    HIDDEN_UNITS,
    CONV1_FILTERS,
    CONV1_KERNEL,
    CONV2_FILTERS,
    CONV2_KERNEL,
    POOL_KERNEL,
    POOL_STRIDE,
)

# Input from the dataloader is (batch, window_size, channels) = (B, 32, 12).
# No BatchNorm: at inference it is only a per-channel affine, which the FPGA
# would have to pay for, and leaving it out keeps this model layer-for-layer
# comparable with QuantCNN in qacnn.py.


class CNN(nn.Module):
    def __init__(self, num_channels=NUM_CHANNELS, num_classes=NUM_CLASSES, hidden_units=HIDDEN_UNITS):
        super(CNN, self).__init__() 

        self.conv1 = nn.Conv1d(num_channels, CONV1_FILTERS, kernel_size=CONV1_KERNEL, padding="same")
        self.relu1 = nn.ReLU()
        # (B, 32, 32) -> (B, 32, 16)
        self.pool = nn.MaxPool1d(kernel_size=POOL_KERNEL, stride=POOL_STRIDE)
        # (B, 32, 16) -> (B, 64, 16)
        self.conv2 = nn.Conv1d(CONV1_FILTERS, CONV2_FILTERS, kernel_size=CONV2_KERNEL, padding="same")
        self.relu2 = nn.ReLU()
        # (B, 64, 16) -> (B, 64, 1)
        self.global_pool = nn.AdaptiveAvgPool1d(1)
        # (B, 64) -> (B, 32) -> (B, 11)
        self.fc1 = nn.Linear(CONV2_FILTERS, hidden_units)
        self.relu3 = nn.ReLU()
        self.fc2 = nn.Linear(hidden_units, num_classes)

    def forward(self, x):
        # x: (B, 32, 12) -> (B, 12, 32), Conv1d expects channels before time
        x = x.transpose(1, 2)

        x = self.relu1(self.conv1(x))
        x = self.pool(x)
        x = self.relu2(self.conv2(x))

        # (B, 64, 1) -> (B, 64)
        x = self.global_pool(x).squeeze(-1)
        x = self.relu3(self.fc1(x))

        # (B, 11) logits
        return self.fc2(x)


def build_model(device):
    model = CNN()
    model.to(device)

    return model


def summarise_model(model, device):
    print("\nModel Summary:")

    # One sample is (window_size, channels); summary adds the batch dimension itself.
    summary(model, input_size=(WINDOW_SIZE, NUM_CHANNELS), device=device.type)
