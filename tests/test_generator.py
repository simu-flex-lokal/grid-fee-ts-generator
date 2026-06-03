import pandas as pd
import pytest

from grid_fee.generator import generate_grid_fee_timeseries
from grid_fee.methods import (
    QuantileDailyBudgetMethod,
    SubscriptionCapacityMethod,
)


def test_generate_grid_fee_timeseries_subscription_without_signal_column():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC"),
        }
    )
    method = SubscriptionCapacityMethod(
        tier_caps_kw=(3.6, 7.0),
        tier_fees=(10.0, 20.0),
        subscribed_tier_index=2,
        penalty_add=2.5,
    )
    result = generate_grid_fee_timeseries(
        frame=frame,
        signal_column=None,
        method=method,
    )
    assert "market_price" not in result.columns
    assert "timestamp" in result.columns
    assert result["grid_fee"].tolist() == [20.0, 20.0, 20.0, 20.0]
    assert result["penalty_threshold_kw"].tolist() == [7.0, 7.0, 7.0, 7.0]


def test_generate_grid_fee_timeseries_rejects_none_signal_for_price_methods():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC"),
        }
    )
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        q_low=0.2,
        q_high=0.2,
    )
    with pytest.raises(ValueError, match="signal_column is required"):
        generate_grid_fee_timeseries(frame=frame, signal_column=None, method=method)


def test_generate_grid_fee_timeseries_returns_expected_schema():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC"),
            "market_price": [10.0, 20.0, 30.0],
        }
    )
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        q_low=0.2,
        q_high=0.2,
    )

    result = generate_grid_fee_timeseries(
        frame=frame,
        signal_column="market_price",
        method=method,
        h0_neutrality_check=False,
    )

    assert list(result.columns) == [
        "timestamp",
        "market_price",
        "grid_fee",
        "is_low_window",
        "is_high_window",
        "window_flag",
        "method",
    ]
    assert result["method"].nunique() == 1
    assert result["method"].iat[0] == "quantile_daily_budget"
    assert set(result["window_flag"].unique()).issubset({0, 1, 2})


def test_generate_grid_fee_timeseries_passes_subscription_penalty_columns():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="1h", tz="UTC"),
            "power_kw": [1.0, 50.0],
        }
    )
    method = SubscriptionCapacityMethod(
        tier_caps_kw=(3.6, 7.0),
        tier_fees=(10.0, 20.0),
        subscribed_tier_index=2,
        penalty_add=2.5,
    )
    result = generate_grid_fee_timeseries(
        frame=frame,
        signal_column="power_kw",
        method=method,
    )
    assert "penalty_threshold_kw" in result.columns
    assert "penalty_rate_per_kw" in result.columns
    assert result["grid_fee"].tolist() == [20.0, 20.0]
    assert result["penalty_threshold_kw"].tolist() == [7.0, 7.0]
    assert result["penalty_rate_per_kw"].tolist() == [2.5, 2.5]
    assert result["method"].iat[0] == "subscription_capacity"


def test_generate_grid_fee_timeseries_is_extensible_with_custom_method():
    class ConstantFeeMethod:
        name = "constant_fee"

        def compute(self, signal: pd.Series, timestamps: pd.Series) -> pd.Series:
            del signal, timestamps
            return pd.Series([7.0, 7.0, 7.0])

    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC"),
            "grid_utilization": [0.2, 0.6, 0.9],
        }
    )

    result = generate_grid_fee_timeseries(
        frame=frame,
        signal_column="grid_utilization",
        method=ConstantFeeMethod(),
        h0_neutrality_check=False,
    )

    assert result["grid_fee"].tolist() == [7.0, 7.0, 7.0]
    assert result["method"].iat[0] == "constant_fee"
    assert set(result["window_flag"].unique()) == {0}
