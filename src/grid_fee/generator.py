from __future__ import annotations

from typing import Protocol

import pandas as pd

from grid_fee.module3_compliance import check_h0_slp_neutrality
from grid_fee.validation import prepare_input_frame


class GridFeeMethod(Protocol):
    """
    Contract for all grid-fee methods.

    A method can either:
    - implement ``compute(...)`` and return only fee values, or
    - implement ``compute_details(...)`` and return fee values plus window metadata.

    Optional class attribute ``uses_input_signal`` (default ``True``): when
    ``False``, ``generate_grid_fee_timeseries`` may be called with
    ``signal_column=None`` and a frame that only contains timestamps.
    """

    name: str

    def compute(self, signal: pd.Series, timestamps: pd.Series) -> pd.Series:
        """Return one fee value per row in signal."""

    def compute_details(self, signal: pd.Series, timestamps: pd.Series) -> pd.DataFrame:
        """Return details including grid_fee and optional metadata columns."""


def generate_grid_fee_timeseries(
    frame: pd.DataFrame,
    signal_column: str | None,
    method: GridFeeMethod,
    timestamp_column: str = "timestamp",
    *,
    h0_neutrality_check: bool = True,
    bdew_profile_path: str | None = None,
    bdew_profile_sheet: str = "H25",
    flat_fee_reference: float | None = None,
    h0_neutrality_tolerance: float = 0.0,
) -> pd.DataFrame:
    """
    Generate a normalized output time series from an input signal.

    ``signal_column`` may be ``None`` only when ``method`` declares
    ``uses_input_signal = False`` (e.g. ``SubscriptionCapacityMethod``). Then
    ``frame`` must contain at least ``timestamp_column``; the output has no
    signal column.

    When ``h0_neutrality_check`` is True (default), runs a BDEW H0-weighted neutrality
    check (``profile_bdew.xlsx``, sheet ``H25``) and emits ``UserWarning`` on violation.

    Output schema:
    - timestamp column (kept from input)
    - signal column (kept from input), unless ``signal_column`` is ``None``
    - grid_fee
    - is_low_window (0/1)
    - is_high_window (0/1)
    - window_flag (0=normal, 1=low, 2=high)
    - method (method name)
    - Optional extra columns from ``compute_details`` (e.g. subscription
      penalty metadata) are passed through unchanged.
    """
    uses_signal = getattr(method, "uses_input_signal", True)
    if signal_column is None and uses_signal:
        raise ValueError(
            "signal_column is required for this method. "
            "Pass signal_column=None only when method.uses_input_signal is False "
            "(e.g. SubscriptionCapacityMethod)."
        )

    prepared = prepare_input_frame(
        frame=frame,
        timestamp_column=timestamp_column,
        signal_column=signal_column,
    )
    if signal_column is None:
        dummy_signal = pd.Series(0.0, index=prepared.index, dtype=float)
        signal_series = dummy_signal
    else:
        signal_series = prepared[signal_column]

    # Prefer rich method output if available (fee + metadata).
    if hasattr(method, "compute_details"):
        details = method.compute_details(
            signal_series,
            prepared[timestamp_column],
        )
    else:
        fees = method.compute(signal_series, prepared[timestamp_column])
        details = pd.DataFrame({"grid_fee": fees.values}, index=prepared.index)

    # Guard against malformed method implementations.
    if len(details) != len(prepared):
        raise ValueError("Fee method returned details with invalid length.")
    if "grid_fee" not in details.columns:
        raise ValueError("Fee method details must include 'grid_fee'.")

    if signal_column is None:
        output = prepared[[timestamp_column]].copy()
    else:
        output = prepared[[timestamp_column, signal_column]].copy()
    output = pd.concat([output, details.reset_index(drop=True)], axis=1)
    # Backfill defaults when a method returns only fee values.
    if "window_flag" not in output.columns:
        output["window_flag"] = 0
    if "is_low_window" not in output.columns:
        output["is_low_window"] = 0
    if "is_high_window" not in output.columns:
        output["is_high_window"] = 0
    output["method"] = method.name

    if h0_neutrality_check:
        check_h0_slp_neutrality(
            output,
            method,
            timestamp_column=timestamp_column,
            flat_fee_reference=flat_fee_reference,
            bdew_profile_path=bdew_profile_path,
            bdew_profile_sheet=bdew_profile_sheet,
            tolerance=h0_neutrality_tolerance,
        )
    return output
