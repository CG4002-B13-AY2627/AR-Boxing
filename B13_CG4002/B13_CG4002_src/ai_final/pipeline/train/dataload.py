import pandas as pd
import torch

from torch.utils.data import Dataset, DataLoader, Subset
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split

from config import (
    DATA_DIR,
    CSV_NAME,
    WINDOW_SIZE,
    BATCH_SIZE,
    TEST_SIZE,
    RANDOM_SEED,
    K_FOLDS,
    PARTICIPANT_COLUMN,
    LABEL_COLUMN,
    FEATURE_COLUMNS,
    LABEL_TO_ID,
)

# We first read the csv file. This should be our data and
# where one row denotes the features, along with the label at the end.

# For this, I want the csv to be of the following format:
# index, participant, l_ax, l_ay, l_az, l_gx, l_gy, l_gz, r_ax, r_ay, r_az, r_gx, r_gy, r_gz, label
# The "height" should be a variable, we decide, but for default, we have it at 32.
# Only the last entry per sample (%32 == 0), contains the label for that feature.
# Other entry "row" does not.
# The participant column appears on every row, and is constant within a window.


class IMUDataset(Dataset):
    def __init__(self, csv_path, window_size=WINDOW_SIZE):
        self.window_size = window_size

        df = pd.read_csv(csv_path)

        required_columns = FEATURE_COLUMNS + [PARTICIPANT_COLUMN, LABEL_COLUMN]
        missing_columns = [
            column for column in required_columns 
            if column not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"Missing columns in CSV: {missing_columns}"
            )

        # We need the amount of rows here to be divisible by window size (obviously)
        if len(df) % window_size != 0:
            raise ValueError(
                f"CSV has {len(df)} rows, which is not divisible by {window_size}"
            )

        # This should be a whole number after the previous check
        self.number_of_samples = len(df) // window_size

        features = df[FEATURE_COLUMNS].to_numpy(dtype="float32")

        self.features = torch.tensor(
            features.reshape(self.number_of_samples, window_size, len(FEATURE_COLUMNS)),
            dtype=torch.float32
        )

        # We collect the labels now.
        last_rows = df.iloc[window_size - 1 :: window_size]

        labels = last_rows[LABEL_COLUMN].tolist()

        # Check that no earlier row contains a label
        # Actually this could be removed (maybe)
        earlier_rows = df.drop(last_rows.index)
        if earlier_rows[LABEL_COLUMN].notna().any():
            raise ValueError(
                "Labels must only appear on the final row of each window."
            )

        # Check that every final row has a valid label
        unknown_labels = [
            label for label in labels
            if label not in LABEL_TO_ID
        ]

        if unknown_labels:
            raise ValueError(
                f"Unknown or missing labels: {unknown_labels}"
            )

        self.labels = torch.tensor(
            [LABEL_TO_ID[label] for label in labels],
            dtype=torch.long,
        )

        # Who recorded each window. A window belongs to exactly one person, so
        # the column has to hold still across all of its rows.
        participants = df[PARTICIPANT_COLUMN].to_numpy()
        participants = participants.reshape(self.number_of_samples, window_size)

        if (participants != participants[:, :1]).any():
            raise ValueError(
                "The participant column changes within a window."
            )

        self.participants = torch.tensor(
            participants[:, 0].astype("int64"),
            dtype=torch.long,
        )

    def __len__(self):
        return self.number_of_samples

    def __getitem__(self, index):
        x = self.features[index]
        y = self.labels[index]

        return x, y

    def participant_ids(self):
        """The distinct participants present, in order."""
        return sorted(set(self.participants.tolist()))


def build_dataset(csv_path=None, window_size=WINDOW_SIZE):
    """Read the csv once and return the windowed dataset."""

    if csv_path is None:
        csv_path = DATA_DIR / CSV_NAME

    return IMUDataset(
        csv_path=csv_path,
        window_size=window_size
    )


def make_loader(dataset, indices, batch_size=BATCH_SIZE, shuffle=False):
    return DataLoader(
        Subset(dataset, indices),
        batch_size=batch_size,
        shuffle=shuffle
    )


def can_stratify(labels, minimum=2):
    """Stratifying needs at least `minimum` windows in the rarest class."""
    return min(labels.count(label) for label in set(labels)) >= minimum


def split_train_test(dataset, test_size=TEST_SIZE, random_seed=RANDOM_SEED):
    labels = dataset.labels.tolist()

    train_indices, test_indices = train_test_split(
        list(range(len(dataset))),
        test_size=test_size,
        random_state=random_seed,
        stratify=labels if can_stratify(labels) else None,
    )

    return sorted(train_indices), sorted(test_indices)


def split_folds(dataset, train_indices, k=K_FOLDS, batch_size=BATCH_SIZE):
    labels = [dataset.labels[index].item() for index in train_indices]

    if can_stratify(labels, minimum=k):
        splitter = StratifiedKFold(n_splits=k, shuffle=True, random_state=RANDOM_SEED)
    else:
        splitter = KFold(n_splits=k, shuffle=True, random_state=RANDOM_SEED)

    folds = []

    for fold_train, fold_val in splitter.split(train_indices, labels):
        # split() gives positions within train_indices, not dataset indices.
        fold_train_indices = [train_indices[position] for position in fold_train]
        fold_val_indices = [train_indices[position] for position in fold_val]

        folds.append((
            make_loader(dataset, fold_train_indices, batch_size, shuffle=True),
            make_loader(dataset, fold_val_indices, batch_size, shuffle=False),
        ))

    return folds


def get_dataloaders(
    csv_path=None,
    window_size=WINDOW_SIZE,
    batch_size=BATCH_SIZE,
    test_size=TEST_SIZE,
    random_seed=RANDOM_SEED,
    k_folds=K_FOLDS,
):
    """Load the windowed IMU csv and return (train_loader, test_loader, folds)."""

    dataset = build_dataset(csv_path, window_size)
    train_indices, test_indices = split_train_test(dataset, test_size, random_seed)

    train_loader = make_loader(dataset, train_indices, batch_size, shuffle=True)
    test_loader = make_loader(dataset, test_indices, batch_size, shuffle=False)

    folds = split_folds(dataset, train_indices, k_folds, batch_size)

    print(f"Number of training windows: {len(train_loader.dataset)}")
    print(f"Number of test windows: {len(test_loader.dataset)}")
    print(f"Number of cross validation folds: {len(folds)}")

    # Purely cosmetic, print out the shape of on batch of data, (the tensor.)

    # Example batch
    x, y = next(iter(train_loader))

    print(x.shape)
    # torch.Size([batch_size, 32, 12])

    print(y.shape)
    # torch.Size([batch_size])

    return train_loader, test_loader, folds


if __name__ == "__main__":
    get_dataloaders()
