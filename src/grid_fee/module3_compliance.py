from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from grid_fee.bdew_profiles import build_bdew_weights_for_timestamps, get_bdew_profile


def _flat_fee_reference(method: Any, override: float | None) -> float:
    if override is not None:
        return float(override)
    if hasattr(method, "base_fee"):
        return float(method.base_fee)
    if hasattr(method, "p_min"):
        return float(method.p_min)
    raise ValueError(
        "Cannot infer flat fee from method; pass flat_fee_reference explicitly."
    )


def check_h0_slp_neutrality(
    result: pd.DataFrame,
    method: Any,
    *,
    timestamp_column: str = "timestamp",
    flat_fee_reference: float | None = None,
    bdew_profile_path: str | Path | None = None,
    bdew_profile_sheet: str = "H25",
    tolerance: float = 0.0,
) -> bool:
    """
    Verify Modul 3 § 14a style H0 neutrality: BDEW-weighted mean ``grid_fee`` ≥ pauschal/ST.

    Uses ``profile_bdew.xlsx`` (default sheet ``H25``). On violation emits ``UserWarning``
    and returns ``False``. Does not modify ``result``.

    Pauschal reference: ``base_fee`` (TopN, Quantile, Subscription) or ``p_min`` (load-linear).
    """
    if "grid_fee" not in result.columns:
        raise ValueError("result must include 'grid_fee'.")
    if timestamp_column not in result.columns:
        raise ValueError(f"result must include {timestamp_column!r}.")

    flat_fee = _flat_fee_reference(method, flat_fee_reference)
    profile = get_bdew_profile(bdew_profile_path, sheet_name=bdew_profile_sheet)
    weights = build_bdew_weights_for_timestamps(result[timestamp_column], profile)
    fees = result["grid_fee"].astype(float)
    if fees.isna().any() or weights.isna().any() or (weights < 0).any():
        raise ValueError("grid_fee and BDEW weights must be non-null and non-negative.")
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        raise ValueError("BDEW weights must sum to a positive value.")

    weighted_avg = float((weights / weight_sum * fees).sum())
    compliant = weighted_avg >= flat_fee - tolerance

    if not compliant:
        warnings.warn(
            f"H0/SLP neutrality violated (profile {profile.profile_code}): "
            f"weighted average grid fee ({weighted_avg:.6g}) is below the flat/ST "
            f"reference ({flat_fee:.6g}) by {flat_fee - weighted_avg:.6g}. "
            "A standard-load-profile customer could pay less than pauschal without "
            "load shifting (Modul 3 § 14a / BDEW).",
            UserWarning,
            stacklevel=2,
        )
    return compliant
