import pandas as pd
import pytest

from grid_fee.methods import (
    LoadLinearDailyMethod,
    QuantileDailyBudgetMethod,
    SubscriptionCapacityMethod,
    TopNPeakReferenceDayMethod,
)


def test_topn_method_respects_peak_count_parameter():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(96), index=range(96), dtype=float)

    method_one = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.3,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=1.0,
        window_size_hours_high=1.0,
        use_reference_day=False,
    )
    method_two = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.3,
        relative_fee_surcharge=0.2,
        n_low_peaks=2,
        n_high_peaks=2,
        window_size_hours_low=1.0,
        window_size_hours_high=1.0,
        use_reference_day=False,
    )

    details_one = method_one.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    details_two = method_two.compute_details(signal=signal, timestamps=pd.Series(timestamps))

    assert (details_two["window_flag"] != 0).sum() > (details_one["window_flag"] != 0).sum()


def test_topn_method_avoids_boundary_peaks_to_keep_full_windows():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(50.0, index=range(len(timestamps)))
    signal.iloc[0] = -100.0

    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=0,
        window_size_hours_low=6.0,
        window_size_hours_high=6.0,
        time_window_start_hour=0,
        time_window_end_hour=23,
        use_reference_day=False,
    )

    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    # Boundary peaks are skipped, so selected windows keep full parametrized length.
    assert (details["window_flag"] != 0).sum() == 24


def test_topn_method_low_wins_when_windows_overlap():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(10.0, index=range(96))
    signal.iloc[40] = -100.0
    signal.iloc[41] = 200.0

    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.5,
        relative_fee_surcharge=0.5,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=4.0,
        window_size_hours_high=4.0,
        use_reference_day=False,
    )

    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    overlap_mask = (details["is_low_window"] == 1) & (details["is_high_window"] == 1)
    assert not overlap_mask.any()


def test_topn_method_keeps_full_window_length_when_possible():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(96), dtype=float)
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=4.0,
        window_size_hours_high=4.0,
        time_window_start_hour=4,
        time_window_end_hour=20,
        use_reference_day=False,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert details["is_low_window"].sum() == 16
    assert details["is_high_window"].sum() == 16


@pytest.mark.parametrize("freq", ["15min", "30min", "1h"])
def test_topn_method_supports_multiple_input_granularities(freq: str):
    timestamps = pd.date_range("2026-01-01", periods=48, freq=freq, tz="UTC")
    signal = pd.Series(range(len(timestamps)), dtype=float)
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=2.0,
        window_size_hours_high=2.0,
        use_reference_day=False,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert len(details) == len(signal)
    assert set(details["window_flag"].unique()).issubset({0, 1, 2})


def test_topn_method_reference_day_with_missing_reference_is_stable():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(len(timestamps)), dtype=float)
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=2.0,
        window_size_hours_high=2.0,
        use_reference_day=True,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert len(details) == len(signal)
    assert set(details["window_flag"].unique()).issubset({0, 1, 2})


def test_topn_method_applies_reference_day_windows_to_target_day():
    # Monday + Tuesday: Tuesday should receive Monday's window positions.
    timestamps = pd.date_range("2026-01-05", periods=96 * 2, freq="15min", tz="UTC")
    signal = pd.Series(50.0, index=range(len(timestamps)))
    # Monday peaks at 06:00 (low) and 18:00 (high)
    signal.iloc[24] = -100.0
    signal.iloc[72] = 200.0
    # Tuesday has flat data so only reference-day mapping can create windows.
    signal.iloc[96:] = 50.0

    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.3,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=2.0,
        window_size_hours_high=2.0,
        use_reference_day=True,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))

    tuesday = details.iloc[96:]
    assert (tuesday["window_flag"] != 0).sum() > 0


def test_topn_method_accepts_zero_peak_configuration():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(96), dtype=float)
    method = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        n_low_peaks=0,
        n_high_peaks=0,
        window_size_hours_low=2.0,
        window_size_hours_high=2.0,
        use_reference_day=False,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert set(details["window_flag"].unique()) == {0}


def test_topn_wider_high_windows_expand_high_mask():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(10.0, index=range(96))
    signal.iloc[40] = -100.0
    signal.iloc[41] = 200.0
    narrow = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.5,
        relative_fee_surcharge=0.5,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=4.0,
        window_size_hours_high=4.0,
        use_reference_day=False,
    )
    wide_high = TopNPeakReferenceDayMethod(
        base_fee=10.0,
        relative_fee_reduction=0.5,
        relative_fee_surcharge=0.5,
        n_low_peaks=1,
        n_high_peaks=1,
        window_size_hours_low=4.0,
        window_size_hours_high=8.0,
        use_reference_day=False,
    )
    d_n = narrow.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    d_w = wide_high.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert d_w["is_high_window"].sum() > d_n["is_high_window"].sum()


def test_quantile_daily_budget_distributed_selects_expected_share():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(96), dtype=float)
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.3,
        q_low=0.25,
        q_high=0.25,
        selection_mode="distributed",
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert details["is_low_window"].sum() == 24
    assert details["is_high_window"].sum() == 24
    assert set(details["window_flag"].unique()).issubset({0, 1, 2})


def test_quantile_daily_budget_contiguous_respects_block_constraints():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series(range(96), dtype=float)
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.3,
        q_low=0.25,
        q_high=0.25,
        selection_mode="contiguous",
        max_blocks_low=2,
        max_blocks_high=2,
        min_block_hours=1.0,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert details["is_low_window"].sum() >= 8
    assert details["is_high_window"].sum() >= 8


@pytest.mark.parametrize("freq", ["15min", "30min", "1h"])
def test_quantile_daily_budget_supports_granularities(freq: str):
    timestamps = pd.date_range("2026-01-01", periods=48, freq=freq, tz="UTC")
    signal = pd.Series(range(len(timestamps)), dtype=float)
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        q_low=0.2,
        q_high=0.2,
        selection_mode="distributed",
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert len(details) == len(signal)


def test_quantile_daily_budget_constant_signal_is_stable():
    timestamps = pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC")
    signal = pd.Series([5.0] * 96)
    method = QuantileDailyBudgetMethod(
        base_fee=10.0,
        relative_fee_reduction=0.2,
        relative_fee_surcharge=0.2,
        q_low=0.1,
        q_high=0.1,
        selection_mode="distributed",
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert set(details["window_flag"].unique()).issubset({0, 1, 2})


def test_load_linear_daily_scales_within_day_bounds():
    timestamps = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    load = pd.Series([0.0, 50.0, 100.0, 100.0])
    method = LoadLinearDailyMethod(p_min=10.0, p_max=30.0)
    details = method.compute_details(signal=load, timestamps=pd.Series(timestamps))
    assert details["grid_fee"].tolist() == [10.0, 20.0, 30.0, 30.0]
    assert set(details["window_flag"].unique()) == {0}


def test_load_linear_daily_is_applied_per_day():
    timestamps = pd.date_range("2026-01-01", periods=4, freq="12h", tz="UTC")
    # day 1: [0, 10] -> maps to [0, 100]
    # day 2: [1000, 1010] -> maps to [0, 100] again (independent scaling)
    load = pd.Series([0.0, 10.0, 1000.0, 1010.0])
    method = LoadLinearDailyMethod(p_min=0.0, p_max=100.0)
    details = method.compute_details(signal=load, timestamps=pd.Series(timestamps))
    assert details["grid_fee"].tolist() == [0.0, 100.0, 0.0, 100.0]


def test_load_linear_daily_constant_day_returns_p_min():
    timestamps = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    load = pd.Series([5.0, 5.0, 5.0, 5.0])
    method = LoadLinearDailyMethod(p_min=7.0, p_max=9.0)
    details = method.compute_details(signal=load, timestamps=pd.Series(timestamps))
    assert details["grid_fee"].tolist() == [7.0, 7.0, 7.0, 7.0]


def test_subscription_capacity_emits_base_fee_and_penalty_metadata():
    timestamps = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    signal = pd.Series([5.0, 7.0, 100.0])
    method = SubscriptionCapacityMethod(
        tier_caps_kw=(3.6, 7.0, 11.0),
        tier_fees=(10.0, 20.0, 30.0),
        subscribed_tier_index=2,
        penalty_add=5.0,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert details["grid_fee"].tolist() == [20.0, 20.0, 20.0]
    assert details["penalty_threshold_kw"].tolist() == [7.0, 7.0, 7.0]
    assert details["penalty_rate_per_kw"].tolist() == [5.0, 5.0, 5.0]
    assert (details["window_flag"] == 0).all()
    assert (details["is_high_window"] == 0).all()


def test_subscription_capacity_signal_values_ignored_for_fee():
    timestamps = pd.date_range("2026-01-01", periods=2, freq="1h", tz="UTC")
    signal = pd.Series([-1.0, 999.0])
    method = SubscriptionCapacityMethod(
        tier_caps_kw=(10.0,),
        tier_fees=(100.0,),
        subscribed_tier_index=1,
        penalty_add=50.0,
    )
    details = method.compute_details(signal=signal, timestamps=pd.Series(timestamps))
    assert (details["grid_fee"] == 100.0).all()
    assert (details["penalty_threshold_kw"] == 10.0).all()
    assert (details["penalty_rate_per_kw"] == 50.0).all()


def test_subscription_capacity_rejects_unsorted_caps():
    with pytest.raises(ValueError, match="strictly increasing"):
        SubscriptionCapacityMethod(
            tier_caps_kw=(11.0, 7.0),
            tier_fees=(1.0, 2.0),
            subscribed_tier_index=1,
            penalty_add=0.0,
        )


def test_subscription_capacity_rejects_invalid_tier_index():
    with pytest.raises(ValueError, match="subscribed_tier_index"):
        SubscriptionCapacityMethod(
            tier_caps_kw=(3.0, 6.0),
            tier_fees=(1.0, 2.0),
            subscribed_tier_index=0,
            penalty_add=0.0,
        )
    with pytest.raises(ValueError, match="subscribed_tier_index"):
        SubscriptionCapacityMethod(
            tier_caps_kw=(3.0, 6.0),
            tier_fees=(1.0, 2.0),
            subscribed_tier_index=3,
            penalty_add=0.0,
        )


def test_subscription_capacity_rejects_mismatched_tier_lengths():
    with pytest.raises(ValueError, match="same length"):
        SubscriptionCapacityMethod(
            tier_caps_kw=(3.0, 6.0),
            tier_fees=(1.0,),
            subscribed_tier_index=1,
            penalty_add=0.0,
        )
