import pytest

from grid_fee.registry import create_method


def test_create_method_returns_topn_peak_reference_day():
    method = create_method(
        "topn_peak_reference_day",
        base_fee=10.0,
        relative_fee_reduction=0.4,
        relative_fee_surcharge=0.2,
        n_low_peaks=1,
        n_high_peaks=3,
    )
    assert method.name == "topn_peak_reference_day"
    assert method.n_low_peaks == 1
    assert method.n_high_peaks == 3
    assert method.window_size_hours_low == 4.0
    assert method.window_size_hours_high == 4.0


def test_create_method_topn_accepts_split_window_sizes_and_legacy():
    split = create_method(
        "topn_peak_reference_day",
        base_fee=10.0,
        relative_fee_reduction=0.4,
        relative_fee_surcharge=0.2,
        window_size_hours_low=2.0,
        window_size_hours_high=6.0,
    )
    assert split.window_size_hours_low == 2.0
    assert split.window_size_hours_high == 6.0
    legacy = create_method(
        "topn_peak_reference_day",
        base_fee=10.0,
        relative_fee_reduction=0.4,
        relative_fee_surcharge=0.2,
        window_size_hours=3.0,
    )
    assert legacy.window_size_hours_low == 3.0
    assert legacy.window_size_hours_high == 3.0


def test_create_method_returns_quantile_daily_budget():
    method = create_method(
        "quantile_daily_budget",
        base_fee=10.0,
        relative_fee_reduction=0.3,
        relative_fee_surcharge=0.2,
        q_low=0.2,
        q_high=0.1,
        selection_mode="contiguous",
        max_blocks_low=2,
        max_blocks_high=1,
        min_block_hours=1.0,
    )
    assert method.name == "quantile_daily_budget"
    assert method.selection_mode == "contiguous"

def test_create_method_returns_load_linear_daily():
    method = create_method(
        "load_linear_daily",
        p_min=10.0,
        p_max=30.0,
    )
    assert method.name == "load_linear_daily"


def test_create_method_returns_subscription_capacity():
    method = create_method(
        "subscription_capacity",
        tier_caps_kw="3.6,7,11",
        tier_fees="10,20,30",
        subscribed_tier_index=2,
        penalty_add=1.5,
    )
    assert method.name == "subscription_capacity"
    assert method.subscribed_cap_kw == 7.0
    assert method.base_fee == 20.0
    assert method.penalty_add == 1.5


def test_create_method_subscription_capacity_accepts_tuple_params():
    method = create_method(
        "subscription_capacity",
        tier_caps_kw=(5.0, 10.0),
        tier_fees=(1.0, 2.0),
        subscribed_tier_index=1,
        penalty_add=0.0,
    )
    assert method.tier_caps_kw == (5.0, 10.0)


def test_create_method_rejects_removed_methods():
    with pytest.raises(ValueError, match="Unknown method"):
        create_method("quantile_dynamic", min_fee=5.0, max_fee=25.0)
    with pytest.raises(ValueError, match="Unknown method"):
        create_method("peak_reference_day", base_fee=10.0)
