import copy

import torch

from tqdm import tqdm

import config

from dataload import get_dataloaders
from normalize import normalize_for_training, save_stats
from cnn import build_model, summarise_model
from qacnn import build_quant_model, transfer_weights
from evaluate import evaluate, report_per_class
from confusion import save_confusion
from loss_curve import plot_loss_curves
from checkpoint import save_checkpoint, quant_checkpoint_name, clear_selected, save_selected
from selection import print_comparison, select_width


def set_seed(seed=config.RANDOM_SEED):
    """Make weight init and shuffling reproducible across runs."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def train_one_epoch(model, train_loader, criterion, optimizer, device):
    """One pass over the training set. Returns the mean loss over its batches."""
    model.train()

    running_loss = 0.0

    for data in train_loader:
        inputs, labels = data[0].to(device), data[1].to(device)
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        running_loss += loss.item()

    return running_loss / len(train_loader)


def validate_one_epoch(model, val_loader, criterion, device):
    """One pass over the validation fold. Returns the mean loss."""
    model.eval()

    running_loss = 0.0

    with torch.no_grad():
        for data in val_loader:
            inputs, labels = data[0].to(device), data[1].to(device)
            outputs = model(inputs)
            loss = criterion(outputs, labels)

            running_loss += loss.item()

    return running_loss / len(val_loader)


def fit_one_fold(
    model,
    fold_train_loader,
    fold_val_loader,
    device,
    num_epochs,
    optimizer_fn,
    description,
    verbose
):
    """Train on one fold. Returns (train_history, val_history, best_val_loss).

    The model is left holding the weights of its best epoch, not its last: with
    early stopping the final epochs are by definition the ones that got worse.
    """
    criterion = config.get_criterion()
    optimizer = optimizer_fn(model)
    scheduler = config.get_scheduler(optimizer)

    loss_history = []
    val_history = []

    best_val_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    epochs_without_improvement = 0

    epochs = tqdm(
        range(num_epochs),
        desc=description,
        unit="epoch",
        disable=not verbose
    )

    for epoch in epochs:
        epoch_loss = train_one_epoch(model, fold_train_loader, criterion, optimizer, device)
        val_loss = validate_one_epoch(model, fold_val_loader, criterion, device)

        loss_history.append(epoch_loss)
        val_history.append(val_loss)

        # Cut the learning rate once validation stops improving.
        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1

        # Purely cosmetic: show the running loss alongside the bar.
        epochs.set_postfix(loss=f"{epoch_loss:.3f}", val=f"{val_loss:.3f}")

        if epochs_without_improvement >= config.EARLY_STOPPING_PATIENCE:
            epochs.close()
            break

    # Restore the best epoch rather than keeping the last one.
    model.load_state_dict(best_state)

    return loss_history, val_history, best_val_loss


def warm_up(model, loader, device):
    """One forward pass, purely so that lazily created parameters exist.

    Brevitas builds an activation quantizer's scale parameter the first time it
    sees data, not in the constructor. Snapshotting a QuantCNN before that has
    happened would capture a state_dict missing those keys, and restoring it
    between folds would then fail.
    """
    model.train()

    inputs = next(iter(loader))[0].to(device)

    with torch.no_grad():
        model(inputs)


def fit(
    model,
    folds,
    device,
    num_epochs=config.NUM_EPOCHS,
    optimizer_fn=None,
    description="Training",
    verbose=True
):
    """Train with k-fold cross validation. Returns (train_history, val_history).

    Every fold starts from the same initial weights, so the folds differ only
    in which participants they validate against. The model is left holding the
    weights of whichever fold reached the lowest validation loss, and the two
    histories returned are that fold's.
    """
    # The QAT runs pass their own optimizer, which uses a smaller step.
    if optimizer_fn is None:
        optimizer_fn = config.get_optimizer

    # Snapshot before any fold touches it. For CNN this is the random init, for
    # QuantCNN it is the transferred FP32 weights. The warm up has to come
    # first, or a QuantCNN's quantizer parameters would not be in the snapshot.
    warm_up(model, folds[0][0], device)
    initial_state = copy.deepcopy(model.state_dict())

    best_fold_loss = float("inf")
    best_state = copy.deepcopy(initial_state)
    best_histories = ([], [])

    for fold_number, (fold_train_loader, fold_val_loader) in enumerate(folds, start=1):
        model.load_state_dict(initial_state)

        loss_history, val_history, val_loss = fit_one_fold(
            model,
            fold_train_loader,
            fold_val_loader,
            device,
            num_epochs,
            optimizer_fn,
            f"{description} fold {fold_number}/{len(folds)}",
            verbose
        )

        if verbose:
            print(
                f"  Fold {fold_number}: best validation loss {val_loss:.4f} "
                f"after {len(val_history)} epochs"
            )

        if val_loss < best_fold_loss:
            best_fold_loss = val_loss
            best_state = copy.deepcopy(model.state_dict())
            best_histories = (loss_history, val_history)

    # Keep the fold that validated best.
    model.load_state_dict(best_state)

    if verbose:
        print(f"  Best validation loss across folds: {best_fold_loss:.4f}")

    return best_histories


def train_fp32(folds, test_loader, device):
    """This is our baseline model, with no QAT."""

    # We first build the model using our @cnn.py class
    model = build_model(device)

    # Print out the model statistics.
    summarise_model(model, device)

    # We first train the model
    loss_history, val_history = fit(model, folds, device, description="FP32")

    # Test on the testset.
    print("\nFP32 baseline on the test set:")
    accuracy = evaluate(model, test_loader, device)
    matrix, names = report_per_class(model, test_loader, device)
    save_confusion(matrix, names, "FP32 baseline", "fp32")

    # Save the model.
    save_checkpoint(model)

    return model, accuracy, loss_history, val_history


def train_quantized(model, folds, test_loader, device, bit_width):
    """Fine-tune one QuantCNN at the given width, starting from the baseline."""
    # Reset the seed per width so shuffling is identical across the sweep and
    # the only thing that differs between runs is the bit width itself.
    set_seed()

    # Build the quantization model.
    quant_model = build_quant_model(device, bit_width, bit_width)
    # We then transfer the weights of our trained baseline, so our quantized model has a starting point.
    quant_model = transfer_weights(model, quant_model)

    # Fit the model.
    loss_history, val_history = fit(
        quant_model,
        folds,
        device,
        num_epochs=config.QAT_NUM_EPOCHS,
        optimizer_fn=config.get_qat_optimizer,
        description=f"QAT w{bit_width}"
    )

    print(f"\nQAT at {bit_width} bits on the test set:")
    accuracy = evaluate(quant_model, test_loader, device)
    matrix, names = report_per_class(quant_model, test_loader, device)
    save_confusion(matrix, names, f"QAT at {bit_width} bits", f"w{bit_width}")

    save_checkpoint(quant_model, quant_checkpoint_name(bit_width))

    return quant_model, accuracy, loss_history, val_history


def main():

    # Set the seed for reproducability.
    set_seed()

    # Move to cuda (if possible)
    device = config.get_device()

    # We get our Dataloader objects. The batch size can be modified in config.py.
    # The get_dataloaders() function prints out statistics of our tensor as well.
    train_loader, test_loader, folds = get_dataloaders()

    # The nodes give us raw IMU readings, but the model only ever sees
    # standardised ones. Fit on the training participants, apply to every
    # window, and save the statistics so the PS can repeat the transform.

    # I realised the name train_loader is quite confusing, as it does not
    # play a part in batching for training, that is folds job. It
    # instead is used to calculate the normalization statistics. but oh wells.
    stats = normalize_for_training(train_loader)
    save_stats(stats)

    # Train to completion first, then look at the curve, then test once.
    model, baseline_accuracy, fp32_history, fp32_val_history = train_fp32(
        folds, test_loader, device
    )

    # Every width starts from the same trained baseline, so the sweep varies
    # only in precision.
    histories = {"FP32 (train)": fp32_history, "FP32 (val)": fp32_val_history}
    results = []

    for bit_width in config.BIT_WIDTH_SWEEP:
        _, accuracy, loss_history, val_history = train_quantized(
            model, folds, test_loader, device, bit_width
        )

        histories[f"QAT w{bit_width} (val)"] = val_history
        results.append((bit_width, accuracy))

    plot_loss_curves(histories)
    print_comparison(baseline_accuracy, results)

    selected = select_width(baseline_accuracy, results)

    if selected is None:
        clear_selected()
        print(
            f"\nNo width stayed within {config.MAX_QUANT_LOSS_PP} pp, "
            f"so {config.QMODEL_DIR.name}/ was emptied rather than left "
            f"holding an earlier run's selection."
        )
    else:
        save_selected(selected)


if __name__ == "__main__":
    main()
