from __future__ import annotations

"""
Core method implementations for dynamic grid-fee generation.

Architecture layers in this module:
1) Selection helpers:
   - choose candidate timestamps (peaks, quantile ranks, block windows)
2) Window materialization:
   - map selected points to concrete timestamp masks
   - enforce day boundaries and conflict resolution
3) Fee mapping:
   - convert low/high masks to actual fee values and output flags
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, Literal

import pandas as pd


def _window_candidate_bounds(
    window_size_hours: float,
    time_window_start_hour: int | None,
    time_window_end_hour: int | None,
) -> tuple[int, int]:
    if time_window_start_hour is not None and time_window_end_hour is not None:
        return time_window_start_hour, time_window_end_hour
    half = window_size_hours / 2.0
    return int(half), int(24 - half)


def select_top_n_non_overlapping_peaks(
    day_df: pd.DataFrame,
    *,
    signal_col: str,
    kind: Literal["min", "max"],
    n_peaks: int,
    window_size_hours: float,
    time_window_start_hour: int | None,
    time_window_end_hour: int | None,
    blocked_peaks: list[pd.Timestamp] | None = None,
) -> list[pd.Timestamp]:
    if n_peaks <= 0:
        return []
    start_hour, end_hour = _window_candidate_bounds(
        window_size_hours=window_size_hours,
        time_window_start_hour=time_window_start_hour,
        time_window_end_hour=time_window_end_hour,
    )
    candidates = day_df[
        (day_df["timestamp"].dt.hour >= start_hour)
        & (day_df["timestamp"].dt.hour <= end_hour)
    ].copy()
    if candidates.empty:
        return []

    # Prefer peaks that keep full windows inside the calendar day.
    half_window = timedelta(hours=window_size_hours / 2.0)
    day_start = candidates["timestamp"].dt.floor("D").iloc[0]
    day_end = day_start + timedelta(days=1)
    candidates = candidates[
        (candidates["timestamp"] - half_window >= day_start)
        & (candidates["timestamp"] + half_window <= day_end)
    ]
    if candidates.empty:
        return []

    ordered = candidates.sort_values(signal_col, ascending=(kind == "min"))
    min_distance = timedelta(hours=window_size_hours)
    blocked_peaks = blocked_peaks or []
    peaks: list[pd.Timestamp] = []
    for _, row in ordered.iterrows():
        candidate = row["timestamp"]
        if any(abs(candidate - blocked) < min_distance for blocked in blocked_peaks):
            continue
        if not any(abs(candidate - existing) < min_distance for existing in peaks):
            peaks.append(candidate)
        if len(peaks) >= n_peaks:
            break
    return sorted(peaks)


def apply_daily_windows_with_clipping(
    timestamps: pd.Series,
    peaks_by_date: dict[object, dict[str, list[pd.Timestamp]]],
    *,
    window_size_hours_low: float,
    window_size_hours_high: float,
    use_reference_day: bool,
    get_reference_day,
) -> tuple[pd.Series, pd.Series]:
    """
    Build day-level boolean masks from selected peak timestamps.

    Important behavior:
    - Supports reference-day transfer by preserving time-of-day offsets.
    - Clamps all windows to `[day_start, day_end)` to avoid spillover.
    - Low peaks use ``window_size_hours_low``; high peaks use ``window_size_hours_high``.
    """
    frame = pd.DataFrame({"timestamp": pd.to_datetime(timestamps, utc=True)})
    frame["date"] = frame["timestamp"].dt.date
    tz = frame["timestamp"].dt.tz

    is_low = pd.Series(False, index=frame.index)
    is_high = pd.Series(False, index=frame.index)

    for date_value in frame["date"].unique():
        current_day = pd.Timestamp(date_value)
        reference_day = (
            get_reference_day(current_day).date() if use_reference_day else date_value
        )
        if reference_day not in peaks_by_date:
            continue

        day_start = pd.Timestamp(date_value)
        if tz is not None:
            day_start = day_start.tz_localize(tz)
        day_end = day_start + timedelta(days=1)

        for label, peaks in (
            ("low", peaks_by_date[reference_day]["min_peaks"]),
            ("high", peaks_by_date[reference_day]["max_peaks"]),
        ):
            for peak in peaks:
                peak_day_start = pd.Timestamp(peak.date())
                if tz is not None:
                    peak_day_start = peak_day_start.tz_localize(tz)

                w_hours = (
                    window_size_hours_low if label == "low" else window_size_hours_high
                )
                half_window = timedelta(hours=w_hours / 2.0)
                start_offset = (peak - half_window) - peak_day_start
                end_offset = (peak + half_window) - peak_day_start

                window_start = day_start + start_offset
                window_end = day_start + end_offset

                clipped_start = max(window_start, day_start)
                clipped_end = min(window_end, day_end)
                if clipped_start >= clipped_end:
                    continue

                mask = (frame["timestamp"] >= clipped_start) & (
                    frame["timestamp"] < clipped_end
                )
                if label == "low":
                    is_low.loc[mask] = True
                else:
                    is_high.loc[mask] = True
    return is_low, is_high


def resolve_window_conflicts_low_wins(
    is_low: pd.Series,
    is_high: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Apply global conflict rule: low windows override high windows."""
    resolved_high = is_high & ~is_low
    return is_low, resolved_high


def _select_quantile_distributed(
    day_signal: pd.Series,
    *,
    q_low: float,
    q_high: float,
) -> tuple[pd.Series, pd.Series]:
    """Distributed mode: select lowest/highest ranked timestamps per day."""
    n_steps = len(day_signal)
    low_count = int(round(n_steps * q_low))
    high_count = int(round(n_steps * q_high))

    low_idx = day_signal.nsmallest(low_count).index if low_count > 0 else pd.Index([])
    high_idx = day_signal.nlargest(high_count).index if high_count > 0 else pd.Index([])

    is_low = pd.Series(False, index=day_signal.index)
    is_high = pd.Series(False, index=day_signal.index)
    is_low.loc[low_idx] = True
    is_high.loc[high_idx] = True
    return is_low, is_high


def _build_contiguous_mask(
    day_signal: pd.Series,
    *,
    target_steps: int,
    prioritize_low: bool,
    max_blocks: int,
    min_block_steps: int,
) -> pd.Series:
    """
    Contiguous mode helper: choose non-overlapping fixed-length blocks.

    Blocks are selected greedily by mean signal score:
    - low windows: minimum block mean
    - high windows: maximum block mean
    """
    if target_steps <= 0 or max_blocks <= 0:
        return pd.Series(False, index=day_signal.index)
    selected = pd.Series(False, index=day_signal.index)
    n = len(day_signal)
    block_len = min(min_block_steps, n)
    target = min(target_steps, max_blocks * block_len)

    blocks = 0
    while blocks < max_blocks and int(selected.sum()) < target:
        scores: list[tuple[float, int]] = []
        for start in range(0, n - block_len + 1):
            end = start + block_len
            if selected.iloc[start:end].any():
                continue
            window = day_signal.iloc[start:end]
            score = window.mean()
            scores.append((score, start))
        if not scores:
            break
        best_score, best_start = (
            min(scores, key=lambda x: x[0])
            if prioritize_low
            else max(scores, key=lambda x: x[0])
        )
        del best_score
        best_end = best_start + block_len
        selected.iloc[best_start:best_end] = True
        blocks += 1
    return selected


def _select_quantile_contiguous(
    day_signal: pd.Series,
    *,
    q_low: float,
    q_high: float,
    max_blocks_low: int,
    max_blocks_high: int,
    min_block_steps: int,
) -> tuple[pd.Series, pd.Series]:
    """Contiguous mode: derive low/high windows as block selections."""
    n_steps = len(day_signal)
    low_steps = int(round(n_steps * q_low))
    high_steps = int(round(n_steps * q_high))
    is_low = _build_contiguous_mask(
        day_signal,
        target_steps=low_steps,
        prioritize_low=True,
        max_blocks=max_blocks_low,
        min_block_steps=min_block_steps,
    )
    blocked_signal = day_signal.copy()
    blocked_signal.loc[is_low] = float("-inf")
    is_high = _build_contiguous_mask(
        blocked_signal,
        target_steps=high_steps,
        prioritize_low=False,
        max_blocks=max_blocks_high,
        min_block_steps=min_block_steps,
    )
    return is_low, is_high


@dataclass(frozen=True)
class TopNPeakReferenceDayMethod:
    """
    Peak-based dynamic windows derived from daily min/max signal peaks.

    For each day, up to n non-overlapping low-price and high-price peaks are selected.
    Windows can optionally be applied from a reference day.
    Low and high peaks may use different half-window lengths for selection and
    for mask construction (``window_size_hours_low`` vs ``window_size_hours_high``).
    """

    base_fee: float
    relative_fee_reduction: float
    relative_fee_surcharge: float
    n_low_peaks: int = 2
    n_high_peaks: int = 2
    window_size_hours_low: float = 4.0
    window_size_hours_high: float = 4.0
    time_window_start_hour: int | None = None
    time_window_end_hour: int | None = None
    use_reference_day: bool = True
    name: str = "topn_peak_reference_day"

    def __post_init__(self) -> None:
        if self.window_size_hours_low <= 0 or self.window_size_hours_high <= 0:
            raise ValueError(
                "window_size_hours_low and window_size_hours_high must be greater than zero."
            )
        if self.n_low_peaks < 0 or self.n_high_peaks < 0:
            raise ValueError("n_low_peaks and n_high_peaks must be >= 0.")
        if self.time_window_start_hour is not None and (
            self.time_window_start_hour < 0 or self.time_window_start_hour > 23
        ):
            raise ValueError("time_window_start_hour must be in range 0..23.")
        if self.time_window_end_hour is not None and (
            self.time_window_end_hour < 0 or self.time_window_end_hour > 23
        ):
            raise ValueError("time_window_end_hour must be in range 0..23.")

    def _get_reference_day(self, date: pd.Timestamp) -> pd.Timestamp:
        weekday = date.weekday()
        if weekday < 5:
            days_back = 1 if weekday > 0 else 3
            return date - timedelta(days=days_back)
        return date - timedelta(days=7)

    def compute_details(self, signal: pd.Series, timestamps: pd.Series) -> pd.DataFrame:
        """
        Compute fee + flags using top-N min/max peaks per day.

        Pipeline:
        - select low/high peaks per day
        - materialize windows (optionally from reference day)
        - resolve conflicts (low wins)
        - map masks to fee values and tri-state flag
        """
        data = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(timestamps, utc=True),
                "signal": signal.astype(float),
            },
            index=signal.index,
        ).sort_values("timestamp")
        data["date"] = data["timestamp"].dt.date

        peak_info: dict[object, dict[str, list[pd.Timestamp]]] = {}
        for date_value, group in data.groupby("date"):
            min_peaks = select_top_n_non_overlapping_peaks(
                group,
                signal_col="signal",
                kind="min",
                n_peaks=self.n_low_peaks,
                window_size_hours=self.window_size_hours_low,
                time_window_start_hour=self.time_window_start_hour,
                time_window_end_hour=self.time_window_end_hour,
            )
            max_peaks = select_top_n_non_overlapping_peaks(
                group,
                signal_col="signal",
                kind="max",
                n_peaks=self.n_high_peaks,
                window_size_hours=self.window_size_hours_high,
                time_window_start_hour=self.time_window_start_hour,
                time_window_end_hour=self.time_window_end_hour,
                blocked_peaks=min_peaks,
            )
            peak_info[date_value] = {
                "min_peaks": min_peaks,
                "max_peaks": max_peaks,
            }

        is_low, is_high = apply_daily_windows_with_clipping(
            timestamps=data["timestamp"],
            peaks_by_date=peak_info,
            window_size_hours_low=self.window_size_hours_low,
            window_size_hours_high=self.window_size_hours_high,
            use_reference_day=self.use_reference_day,
            get_reference_day=self._get_reference_day,
        )
        is_low, is_high = resolve_window_conflicts_low_wins(is_low=is_low, is_high=is_high)

        fee = pd.Series(self.base_fee, index=data.index, dtype=float)
        fee.loc[is_high] = self.base_fee * (1.0 + self.relative_fee_surcharge)
        fee.loc[is_low] = self.base_fee * (1.0 - self.relative_fee_reduction)

        details = pd.DataFrame(
            {
                "grid_fee": fee.values,
                "is_low_window": is_low.astype(int).values,
                "is_high_window": is_high.astype(int).values,
                "window_flag": pd.Series(
                    0,
                    index=data.index,
                    dtype=int,
                )
                .mask(is_low, 1)
                .mask(is_high, 2)
                .values,
            },
            index=data.index,
        )
        return details.loc[signal.index]

@dataclass(frozen=True)
class QuantileDailyBudgetMethod:
    """
    Quantile-based daily budget method.

    - `q_low` / `q_high` define day-level low/high activation shares.
    - `selection_mode='distributed'` picks individual ranked timestamps.
    - `selection_mode='contiguous'` builds operationally manageable blocks.
    """
    base_fee: float
    relative_fee_reduction: float
    relative_fee_surcharge: float
    q_low: float
    q_high: float
    selection_mode: Literal["distributed", "contiguous"] = "distributed"
    max_blocks_low: int = 2
    max_blocks_high: int = 2
    min_block_hours: float = 1.0
    name: str = "quantile_daily_budget"

    def __post_init__(self) -> None:
        if not (0.0 <= self.q_low <= 1.0 and 0.0 <= self.q_high <= 1.0):
            raise ValueError("q_low and q_high must be in range [0, 1].")
        if self.selection_mode not in {"distributed", "contiguous"}:
            raise ValueError("selection_mode must be 'distributed' or 'contiguous'.")
        if self.max_blocks_low <= 0 or self.max_blocks_high <= 0:
            raise ValueError("max_blocks_low and max_blocks_high must be > 0.")
        if self.min_block_hours <= 0:
            raise ValueError("min_block_hours must be > 0.")

    def compute_details(self, signal: pd.Series, timestamps: pd.Series) -> pd.DataFrame:
        """Compute fee + flags with per-day quantile budget selection."""
        data = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(timestamps, utc=True),
                "signal": signal.astype(float),
            },
            index=signal.index,
        ).sort_values("timestamp")
        data["date"] = data["timestamp"].dt.date

        is_low = pd.Series(False, index=data.index)
        is_high = pd.Series(False, index=data.index)

        for _, day_df in data.groupby("date"):
            day_signal = day_df["signal"]
            if self.selection_mode == "distributed":
                day_low, day_high = _select_quantile_distributed(
                    day_signal,
                    q_low=self.q_low,
                    q_high=self.q_high,
                )
            else:
                diffs = day_df["timestamp"].diff().dropna()
                step_hours = (
                    diffs.median().total_seconds() / 3600.0 if not diffs.empty else 1.0
                )
                min_block_steps = max(1, int(round(self.min_block_hours / step_hours)))
                day_low, day_high = _select_quantile_contiguous(
                    day_signal,
                    q_low=self.q_low,
                    q_high=self.q_high,
                    max_blocks_low=self.max_blocks_low,
                    max_blocks_high=self.max_blocks_high,
                    min_block_steps=min_block_steps,
                )
            is_low.loc[day_df.index] = day_low
            is_high.loc[day_df.index] = day_high

        is_low, is_high = resolve_window_conflicts_low_wins(is_low=is_low, is_high=is_high)
        fee = pd.Series(self.base_fee, index=data.index, dtype=float)
        fee.loc[is_high] = self.base_fee * (1.0 + self.relative_fee_surcharge)
        fee.loc[is_low] = self.base_fee * (1.0 - self.relative_fee_reduction)

        details = pd.DataFrame(
            {
                "grid_fee": fee.values,
                "is_low_window": is_low.astype(int).values,
                "is_high_window": is_high.astype(int).values,
                "window_flag": pd.Series(0, index=data.index, dtype=int)
                .mask(is_low, 1)
                .mask(is_high, 2)
                .values,
            },
            index=data.index,
        )
        return details.loc[signal.index]


@dataclass(frozen=True)
class LoadLinearDailyMethod:
    """
    Load-dependent dynamic grid fee based on daily min/max normalization.

    Mathematical formulation (per day j):

      P_tj = (NL_tj - min(NL_j)) * (P_max - P_min) / (max(NL_j) - min(NL_j)) + P_min

    Where:
    - NL_tj is the net load signal at timestamp t of day j
    - NL_j is the set of all net load values for the day
    - P_min / P_max are the daily lower/upper bounds for the grid fee
    """

    p_min: float
    p_max: float
    name: str = "load_linear_daily"

    def __post_init__(self) -> None:
        if self.p_max < self.p_min:
            raise ValueError("p_max must be greater than or equal to p_min.")

    def compute_details(self, signal: pd.Series, timestamps: pd.Series) -> pd.DataFrame:
        data = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(timestamps, utc=True),
                "signal": signal.astype(float),
            },
            index=signal.index,
        ).sort_values("timestamp")
        data["date"] = data["timestamp"].dt.date

        fee = pd.Series(index=data.index, dtype=float)
        for _, day_df in data.groupby("date"):
            day_signal = day_df["signal"]
            day_min = float(day_signal.min())
            day_max = float(day_signal.max())
            spread = day_max - day_min
            if spread == 0:
                fee.loc[day_df.index] = float(self.p_min)
            else:
                fee.loc[day_df.index] = (
                    (day_signal - day_min) * (self.p_max - self.p_min) / spread
                    + self.p_min
                )

        zeros = pd.Series(0, index=data.index, dtype=int)
        details = pd.DataFrame(
            {
                "grid_fee": fee.values,
                "is_low_window": zeros.values,
                "is_high_window": zeros.values,
                "window_flag": zeros.values,
            },
            index=data.index,
        )
        return details.loc[signal.index]


@dataclass(frozen=True)
class SubscriptionCapacityMethod:
    """
    Subscription-tier base grid fee plus linear-penalty metadata (no signal use).

    The tier menu is configuration only: each tier has a subscribed cap (kW)
    and a base fee; ``subscribed_tier_index`` (1-based) selects the contract.

    ``grid_fee`` is the constant base fee for that tier. This method does **not**
    read the power ``signal``; overrun penalisation is deferred to downstream
    code. The class sets ``uses_input_signal = False`` so
    ``generate_grid_fee_timeseries(..., signal_column=None)`` can be used with a
    timestamp-only input frame. Each row therefore includes:

    - ``penalty_threshold_kw``: subscribed power cap (kW) from which overage is
      measured (same as ``subscribed_cap_kw``).
    - ``penalty_rate_per_kw``: slope for a linear surcharge, equal to the
      constructor argument ``penalty_add`` (fee increment per kW of overage).

    A typical external composition is
    ``total = grid_fee + max(0, P - penalty_threshold_kw) * penalty_rate_per_kw``
    with an exogenous or simulated ``P`` in kW, using the same units as
    ``grid_fee`` for the product term.
    """

    tier_caps_kw: tuple[float, ...]
    tier_fees: tuple[float, ...]
    subscribed_tier_index: int
    penalty_add: float
    name: str = "subscription_capacity"
    uses_input_signal: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if len(self.tier_caps_kw) != len(self.tier_fees):
            raise ValueError(
                "tier_caps_kw and tier_fees must have the same length (one entry per tier)."
            )
        if not self.tier_caps_kw:
            raise ValueError("At least one subscription tier is required.")
        if self.subscribed_tier_index < 1 or self.subscribed_tier_index > len(
            self.tier_caps_kw
        ):
            raise ValueError(
                "subscribed_tier_index must be between 1 and the number of tiers."
            )
        if self.penalty_add < 0:
            raise ValueError("penalty_add must be non-negative.")
        prev = None
        for cap in self.tier_caps_kw:
            if cap != cap or not cap < float("inf"):
                raise ValueError("tier_caps_kw entries must be finite floats.")
            if prev is not None and cap <= prev:
                raise ValueError("tier_caps_kw must be strictly increasing.")
            prev = cap
        for fee in self.tier_fees:
            if fee != fee:
                raise ValueError("tier_fees entries must be finite floats.")

    @property
    def subscribed_cap_kw(self) -> float:
        return float(self.tier_caps_kw[self.subscribed_tier_index - 1])

    @property
    def base_fee(self) -> float:
        return float(self.tier_fees[self.subscribed_tier_index - 1])

    def compute_details(self, signal: pd.Series, timestamps: pd.Series) -> pd.DataFrame:
        index = signal.index
        cap = self.subscribed_cap_kw
        f_base = self.base_fee
        rate = float(self.penalty_add)

        fee = pd.Series(f_base, index=index, dtype=float)
        threshold_col = pd.Series(cap, index=index, dtype=float)
        rate_col = pd.Series(rate, index=index, dtype=float)
        zeros = pd.Series(0, index=index, dtype=int)

        details = pd.DataFrame(
            {
                "grid_fee": fee.values,
                "penalty_threshold_kw": threshold_col.values,
                "penalty_rate_per_kw": rate_col.values,
                "is_low_window": zeros.values,
                "is_high_window": zeros.values,
                "window_flag": zeros.values,
            },
            index=index,
        )
        return details


_METHOD_IDS: tuple[str, ...] = (
    "topn_peak_reference_day",
    "quantile_daily_budget",
    "load_linear_daily",
    "subscription_capacity",
)


def create_methods_from_config(
    config: Mapping[str, Mapping[str, object]],
) -> dict[
    str,
    TopNPeakReferenceDayMethod
    | QuantileDailyBudgetMethod
    | LoadLinearDailyMethod
    | SubscriptionCapacityMethod,
]:
    """
    Build all four built-in grid-fee methods from a nested parameter mapping.

    ``config`` keys must be the method IDs (e.g. from
    :func:`grid_fee.method_config.load_methods_config_from_excel`).
    Each value is a flat dict of parameter names to values passed to
    :func:`grid_fee.registry.create_method`.
    """
    from grid_fee.method_config import METHOD_SHEET_NAMES
    from grid_fee.registry import create_method

    expected = set(METHOD_SHEET_NAMES)
    provided = set(config)
    missing = expected - provided
    if missing:
        missing_repr = ", ".join(sorted(missing))
        raise ValueError(f"Method config is missing method(s): {missing_repr}.")
    unknown = provided - expected
    if unknown:
        unknown_repr = ", ".join(sorted(unknown))
        raise ValueError(f"Method config contains unknown method(s): {unknown_repr}.")

    methods: dict[
        str,
        TopNPeakReferenceDayMethod
        | QuantileDailyBudgetMethod
        | LoadLinearDailyMethod
        | SubscriptionCapacityMethod,
    ] = {}
    for method_id in _METHOD_IDS:
        params = dict(config[method_id])
        methods[method_id] = create_method(method_id, **params)
    return methods
