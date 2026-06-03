from pathlib import Path

import pandas as pd
import pytest

from grid_fee.bdew_profiles import (
    build_bdew_weights_for_timestamps,
    classify_bdew_day_type,
    get_bdew_profile,
    load_bdew_profile_xlsx,
)

BDEW_XLSX = Path(__file__).resolve().parents[1] / "profile_bdew.xlsx"


pytestmark = pytest.mark.skipif(
    not BDEW_XLSX.is_file(),
    reason="profile_bdew.xlsx not in project root",
)


def test_load_bdew_profile_h25():
    profile = load_bdew_profile_xlsx(BDEW_XLSX, sheet_name="H25")
    assert profile.profile_code
    assert profile.weight(1, "WT", 0) > 0
    assert len(profile.values) == 12


def test_build_bdew_weights_for_15min_day():
    profile = get_bdew_profile(BDEW_XLSX, sheet_name="H25")
    ts = pd.date_range("2026-01-06", periods=96, freq="15min", tz="UTC")  # Tuesday WT
    weights = build_bdew_weights_for_timestamps(ts, profile)
    assert len(weights) == 96
    assert weights.sum() > 0


def test_classify_bdew_day_type_saturday():
    ts = pd.Timestamp("2026-01-03 12:00:00", tz="UTC")  # Saturday
    assert classify_bdew_day_type(ts) == "SA"
