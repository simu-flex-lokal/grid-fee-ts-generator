from __future__ import annotations

import pandas as pd


def prepare_input_frame(
    frame: pd.DataFrame,
    timestamp_column: str,
    signal_column: str | None,
) -> pd.DataFrame:
    """
    Validate and normalize the minimal input schema.

    Validation guarantees:
    - ``timestamp_column`` exists, is parsed as UTC datetime, sorted, unique
    - if ``signal_column`` is set: column exists and values are non-null

    When ``signal_column`` is ``None``, only timestamps are returned (for methods
    that do not consume an input signal, e.g. ``SubscriptionCapacityMethod``).
    """
    if timestamp_column not in frame.columns:
        raise ValueError(f"Missing required column: {timestamp_column!r}")

    if signal_column is None:
        prepared = frame[[timestamp_column]].copy()
        prepared[timestamp_column] = pd.to_datetime(prepared[timestamp_column], utc=True)
        prepared = prepared.sort_values(timestamp_column).reset_index(drop=True)
        if prepared[timestamp_column].duplicated().any():
            raise ValueError("Timestamps must be unique.")
        return prepared

    missing_columns = [
        col for col in (timestamp_column, signal_column) if col not in frame.columns
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Missing required column(s): {missing}")

    prepared = frame[[timestamp_column, signal_column]].copy()
    prepared[timestamp_column] = pd.to_datetime(prepared[timestamp_column], utc=True)
    prepared = prepared.sort_values(timestamp_column).reset_index(drop=True)

    if prepared[timestamp_column].duplicated().any():
        raise ValueError("Timestamps must be unique.")
    if prepared[signal_column].isna().any():
        raise ValueError("Signal column must not contain null values.")

    return prepared
