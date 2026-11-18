import torch

from sklearn.metrics import classification_report, confusion_matrix

from config import ID_TO_LABEL


def collect_predictions(model, loader, device):
    """Run the model over a loader. Returns (predictions, labels) as tensors."""
    # BatchNorm must use its learned running statistics, not batch statistics.
    # For QuantCNN this also freezes the activation quantizers, which calibrate
    # their scales from what they see while training.
    model.eval()

    all_predicted = []
    all_labels = []

    # No gradients needed for inference.
    with torch.no_grad():
        for data in loader:
            inputs, labels = data[0].to(device), data[1].to(device)
            outputs = model(inputs)

            _, predicted = torch.max(outputs, 1)

            all_predicted.append(predicted.cpu())
            all_labels.append(labels.cpu())

    return torch.cat(all_predicted), torch.cat(all_labels)


def evaluate(model, loader, device, verbose=True):
    """Accuracy over a held-out set. Returns the fraction correct."""
    predicted, labels = collect_predictions(model, loader, device)

    total = labels.size(0)                          # Windows evaluated.
    correct = (predicted == labels).sum().item()    # Windows classified correctly.

    accuracy = correct / total

    if verbose:
        print(f"Accuracy: {100 * accuracy:.2f}%")

    return accuracy


def report_per_class(model, loader, device):
    """Per-class precision and recall, plus the confusion matrix.

    Section 5.4.5 asks for at least 85% precision and recall on every class,
    and Section 5.2.2 asks that quantization loss is not concentrated in one
    action. Overall accuracy alone answers neither question.

    Returns (matrix, names), the names labelling its rows and columns.
    """
    predicted, labels = collect_predictions(model, loader, device)

    present = sorted(set(labels.tolist()) | set(predicted.tolist()))
    names = [ID_TO_LABEL[index] for index in present]

    print(classification_report(
        labels,
        predicted,
        labels=present,
        target_names=names,
        zero_division=0
    ))

    matrix = confusion_matrix(labels, predicted, labels=present)

    print("Confusion matrix (rows are true, columns are predicted):")
    print(matrix)

    return matrix, names
