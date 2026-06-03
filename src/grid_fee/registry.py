from __future__ import annotations

from grid_fee.methods import (
    TopNPeakReferenceDayMethod,
    QuantileDailyBudgetMethod,
    LoadLinearDailyMethod,
    SubscriptionCapacityMethod,
)


def _float_tuple_param(value: object, *, label: str) -> tuple[float, ...]:
    if value is None:
        raise ValueError(f"Parameter '{label}' is required.")
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts:
            raise ValueError(f"Parameter '{label}' must contain at least one number.")
        return tuple(float(p) for p in parts)
    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError(f"Parameter '{label}' must contain at least one number.")
        return tuple(float(x) for x in value)
    raise TypeError(f"Parameter '{label}' must be a comma-separated string, list, or tuple.")


def create_method(method_name: str, **params: object):
    """
    Factory for built-in methods.

    The registry is the single place where string method IDs are mapped
    to concrete classes and where high-level parameter validation happens.
    """
    normalized = method_name.strip().lower()
    if normalized == "topn_peak_reference_day":
        required = [
            "base_fee",
            "relative_fee_reduction",
            "relative_fee_surcharge",
        ]
        missing = [name for name in required if params.get(name) is None]
        if missing:
            missing_repr = ", ".join(missing)
            raise ValueError(
                "Parameter(s) required for topn_peak_reference_day are missing: "
                f"{missing_repr}."
            )
        common_ws = float(params.get("window_size_hours", 4.0))
        w_low = (
            float(params["window_size_hours_low"])
            if params.get("window_size_hours_low") is not None
            else common_ws
        )
        w_high = (
            float(params["window_size_hours_high"])
            if params.get("window_size_hours_high") is not None
            else common_ws
        )
        return TopNPeakReferenceDayMethod(
            base_fee=float(params["base_fee"]),
            relative_fee_reduction=float(params["relative_fee_reduction"]),
            relative_fee_surcharge=float(params["relative_fee_surcharge"]),
            n_low_peaks=int(params.get("n_low_peaks", 2)),
            n_high_peaks=int(params.get("n_high_peaks", 2)),
            window_size_hours_low=w_low,
            window_size_hours_high=w_high,
            time_window_start_hour=(
                int(params["time_window_start_hour"])
                if params.get("time_window_start_hour") is not None
                else None
            ),
            time_window_end_hour=(
                int(params["time_window_end_hour"])
                if params.get("time_window_end_hour") is not None
                else None
            ),
            use_reference_day=bool(params.get("use_reference_day", True)),
        )
    if normalized == "quantile_daily_budget":
        required = [
            "base_fee",
            "relative_fee_reduction",
            "relative_fee_surcharge",
            "q_low",
            "q_high",
        ]
        missing = [name for name in required if params.get(name) is None]
        if missing:
            missing_repr = ", ".join(missing)
            raise ValueError(
                "Parameter(s) required for quantile_daily_budget are missing: "
                f"{missing_repr}."
            )
        return QuantileDailyBudgetMethod(
            base_fee=float(params["base_fee"]),
            relative_fee_reduction=float(params["relative_fee_reduction"]),
            relative_fee_surcharge=float(params["relative_fee_surcharge"]),
            q_low=float(params["q_low"]),
            q_high=float(params["q_high"]),
            selection_mode=str(params.get("selection_mode", "distributed")),
            max_blocks_low=int(params.get("max_blocks_low", 2)),
            max_blocks_high=int(params.get("max_blocks_high", 2)),
            min_block_hours=float(params.get("min_block_hours", 1.0)),
        )
    if normalized == "load_linear_daily":
        required = [
            "p_min",
            "p_max",
        ]
        missing = [name for name in required if params.get(name) is None]
        if missing:
            missing_repr = ", ".join(missing)
            raise ValueError(
                "Parameter(s) required for load_linear_daily are missing: "
                f"{missing_repr}."
            )
        return LoadLinearDailyMethod(
            p_min=float(params["p_min"]),
            p_max=float(params["p_max"]),
        )
    if normalized == "subscription_capacity":
        required = [
            "tier_caps_kw",
            "tier_fees",
            "subscribed_tier_index",
            "penalty_add",
        ]
        missing = [name for name in required if params.get(name) is None]
        if missing:
            missing_repr = ", ".join(missing)
            raise ValueError(
                "Parameter(s) required for subscription_capacity are missing: "
                f"{missing_repr}."
            )
        return SubscriptionCapacityMethod(
            tier_caps_kw=_float_tuple_param(params["tier_caps_kw"], label="tier_caps_kw"),
            tier_fees=_float_tuple_param(params["tier_fees"], label="tier_fees"),
            subscribed_tier_index=int(params["subscribed_tier_index"]),
            penalty_add=float(params["penalty_add"]),
        )
    raise ValueError(
        "Unknown method. Supported methods: "
        "'topn_peak_reference_day', 'quantile_daily_budget', 'load_linear_daily', "
        "'subscription_capacity'."
    )
