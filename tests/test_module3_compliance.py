import warnings
from pathlib import Path

import pandas as pd
import pytest

from grid_fee.generator import generate_grid_fee_timeseries
from grid_fee.methods import (
    LoadLinearDailyMethod,
    QuantileDailyBudgetMethod,
    SubscriptionCapacityMethod,
    TopNPeakReferenceDayMethod,
)
from grid_fee.module3_compliance import check_h0_slp_neutrality

BDEW_XLSX = Path(__file__).resolve().parents[1] / "profile_bdew.xlsx"
has_bdew = BDEW_XLSX.is_file()


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_check_h0_slp_neutrality_compliant_constant_fee():
    timestamps = pd.date_range("2026-01-06", periods=96, freq="15min", tz="UTC")
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.0,
        relative_fee_surcharge=0.0,
        n_low_peaks=0,
        n_high_peaks=0,
        use_reference_day=False,
    )
    result = generate_grid_fee_timeseries(
        frame=pd.DataFrame({"timestamp": timestamps, "signal": range(96)}),
        signal_column="signal",
        method=method,
        h0_neutrality_check=False,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert check_h0_slp_neutrality(result, method) is True
    assert len(caught) == 0


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_check_h0_slp_neutrality_warns_on_violation():
    timestamps = pd.date_range("2026-01-06", periods=96, freq="15min", tz="UTC")
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.95,
        relative_fee_surcharge=0.01,
        n_low_peaks=3,
        n_high_peaks=1,
        window_size_hours_low=8.0,
        window_size_hours_high=1.0,
        use_reference_day=False,
    )
    result = generate_grid_fee_timeseries(
        frame=pd.DataFrame({"timestamp": timestamps, "signal": range(96)}),
        signal_column="signal",
        method=method,
        h0_neutrality_check=False,
    )
    with pytest.warns(UserWarning, match="neutrality violated"):
        assert check_h0_slp_neutrality(result, method) is False


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_generator_runs_check_without_extra_columns():
    timestamps = pd.date_range("2026-01-06", periods=96, freq="15min", tz="UTC")
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        q_low=0.1,
        q_high=0.1,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result = generate_grid_fee_timeseries(
            frame=pd.DataFrame({"timestamp": timestamps, "signal": range(96)}),
            signal_column="signal",
            method=method,
        )
    assert "h0_neutrality_compliant" not in result.columns
    assert "grid_fee" in result.columns


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_flat_fee_reference_load_linear_uses_p_min():
    timestamps = pd.date_range("2026-01-06", periods=96, freq="15min", tz="UTC")
    method = LoadLinearDailyMethod(p_min=10.0, p_max=30.0)
    result = generate_grid_fee_timeseries(
        frame=pd.DataFrame({"timestamp": timestamps, "signal": range(96)}),
        signal_column="signal",
        method=method,
        h0_neutrality_check=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        check_h0_slp_neutrality(result, method)


def test_generator_can_disable_h0_check():
    timestamps = pd.date_range("2026-01-06", periods=4, freq="1h", tz="UTC")
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.95,
        relative_fee_surcharge=0.01,
        use_reference_day=False,
    )
    result = generate_grid_fee_timeseries(
        frame=pd.DataFrame({"timestamp": timestamps, "signal": [1, 2, 3, 4]}),
        signal_column="signal",
        method=method,
        h0_neutrality_check=False,
    )
    assert "h0_neutrality_compliant" not in result.columns
