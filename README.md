# grid-fee-ts-generator

Python library for **dynamic grid fee time series**: you provide timestamps and an **exogenous** signal (day-ahead price, forecast load, grid stress, etc.), choose a tariff method, and get a per-timestep `grid_fee` plus window flags.

The package does **not** model how customers react to prices. Fee logic runs in one direction (signal → fee). Load shifting or market coupling belongs in a separate simulation step.

**Requirements:** Python 3.11+, pandas. For the built-in H0 neutrality check: `profile_bdew.xlsx` in the project root (BDEW standard load profiles).

Examples: [notebooks/time_window_dynamic_grid_fee.ipynb](notebooks/time_window_dynamic_grid_fee.ipynb).

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```python
import pandas as pd
from grid_fee import TopNPeakReferenceDayMethod, generate_grid_fee_timeseries

frame = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=96, freq="15min", tz="UTC"),
    "market_price": [...],  # your signal, one value per row
})

method = TopNPeakReferenceDayMethod(
    base_fee=12.0,                    # normal (ST) fee
    relative_fee_reduction=0.4,         # discount in low windows (NT)
    relative_fee_surcharge=0.2,         # surcharge in high windows (HT)
    n_low_peaks=2,
    n_high_peaks=2,
    window_size_hours_low=4.0,
    window_size_hours_high=4.0,
)

result = generate_grid_fee_timeseries(frame, signal_column="market_price", method=method)
```

## Output

Every run returns a DataFrame aligned with your input:

| Column | Meaning |
|--------|---------|
| `timestamp` | From input (normalized to UTC) |
| signal column | Your input series (omitted for subscription-only runs) |
| `grid_fee` | Grid fee at that timestep |
| `is_low_window` / `is_high_window` | 0 or 1 |
| `window_flag` | `0` normal, `1` low (NT), `2` high (HT) |
| `method` | Method name string |

Some methods add extra columns (e.g. subscription penalty metadata). Timestamps must be **unique** and the signal must be **non-null** where required.

## Methods

| Method | Idea | Typical signal |
|--------|------|----------------|
| **TopNPeakReferenceDayMethod** | Daily top-N low/high peaks; symmetric windows around each peak; optional “yesterday’s peaks apply today” | Price, utilization |
| **QuantileDailyBudgetMethod** | Each day, a share `q_low` / `q_high` of timesteps become low/high windows (`distributed` or `contiguous` blocks) | Price, utilization |
| **LoadLinearDailyMethod** | Per day, map signal linearly from daily min→max to fee band `p_min`→`p_max` (no NT/HT windows) | Load, utilization |
| **SubscriptionCapacityMethod** | Fixed base fee from a chosen contract tier; emits penalty threshold/rate for **external** linear overrun checks (does not use signal for fee) | Timestamps only, or any column ignored |

Create instances in Python (as above) or by name:

```python
from grid_fee import create_method

method = create_method(
    "quantile_daily_budget",
    base_fee=12.0,
    relative_fee_reduction=0.4,
    relative_fee_surcharge=0.2,
    q_low=0.15,
    q_high=0.15,
    selection_mode="contiguous",
)
```

Supported names: `topn_peak_reference_day`, `quantile_daily_budget`, `load_linear_daily`, `subscription_capacity`.

### Configure via Excel

Edit [examples/method_config.xlsx](examples/method_config.xlsx): one sheet per method with columns `parameter`, `value`, and `description`. Empty value cells use registry defaults.

```python
from grid_fee import (
    load_methods_config_from_excel,
    create_methods_from_config,
    generate_grid_fee_timeseries,
)

config = load_methods_config_from_excel("examples/method_config.xlsx")
methods = create_methods_from_config(config)

result = generate_grid_fee_timeseries(
    frame,
    signal_column="market_price",
    method=methods["topn_peak_reference_day"],
)
```

You can also pass a dict directly to `create_methods_from_config` without Excel. Regenerate the template after parameter changes with `python scripts/generate_method_config_template.py`.

### Window methods (TopN & Quantile)

Shared rules:

- Works with 15‑min, 30‑min, hourly, or other **regular** steps.
- Low/high windows stay inside the calendar day.
- If low and high overlap, **low wins**.
- Peak-based windows do not overlap within the same side (low or high).

Fees: `grid_fee = base_fee` (normal), `base_fee × (1 − reduction)` (low), `base_fee × (1 + surcharge)` (high).

## SLP neutrality check (Modul 3 § 14a EnWg)

By default, each `generate_grid_fee_timeseries` call checks that the **BDEW household profile** (sheet `H25` in `profile_bdew.xlsx`) does not yield a **lower** average fee than the pauschal reference (`base_fee` or `p_min`). On violation you get a `UserWarning` only—no extra output columns.

```python
# Disable if needed
result = generate_grid_fee_timeseries(..., h0_neutrality_check=False)

# Optional explicit re-check (returns True/False)
from grid_fee import check_h0_slp_neutrality
check_h0_slp_neutrality(result, method)
```

Other BDEW sheets: `G25`, `L25`, `P25`, `S25` via `bdew_profile_sheet="G25"` on `generate_grid_fee_timeseries`.

## Tests

```bash
pytest -q
```
