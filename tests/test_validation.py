import pandas as pd
import pytest

from grid_fee.validation import prepare_input_frame


def test_prepare_input_frame_timestamp_only_schema():
    frame = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T01:00:00Z", "2026-01-01T00:00:00Z"],
        }
    )
    prepared = prepare_input_frame(
        frame, timestamp_column="timestamp", signal_column=None
    )
    assert list(prepared.columns) == ["timestamp"]
    assert prepared["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 00:00:00", tz="UTC")


def test_prepare_input_frame_fails_on_missing_columns():
    frame = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"]})

    with pytest.raises(ValueError, match="Missing required column"):
        prepare_input_frame(frame, timestamp_column="timestamp", signal_column="signal")


def test_prepare_input_frame_fails_on_duplicate_timestamps():
    frame = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
            "signal": [1.0, 2.0],
        }
    )

    with pytest.raises(ValueError, match="Timestamps must be unique"):
        prepare_input_frame(frame, timestamp_column="timestamp", signal_column="signal")


def test_prepare_input_frame_sorts_and_normalizes_timestamps():
    frame = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T01:00:00Z", "2026-01-01T00:00:00Z"],
            "signal": [2.0, 1.0],
        }
    )

    prepared = prepare_input_frame(
        frame,
        timestamp_column="timestamp",
        signal_column="signal",
    )
    assert prepared["signal"].tolist() == [1.0, 2.0]
