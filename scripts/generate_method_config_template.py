#!/usr/bin/env python3
"""Regenerate examples/method_config.xlsx from canonical parameter defaults."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "examples" / "method_config.xlsx"

SHEET_ROWS: dict[str, list[tuple[str, object, str]]] = {
    "topn_peak_reference_day": [
        ("base_fee", 12.0, "Normal (ST) grid fee"),
        ("relative_fee_reduction", 0.4, "Discount factor in low windows (fee = base × (1 − reduction))"),
        ("relative_fee_surcharge", 0.2, "Surcharge factor in high windows (fee = base × (1 + surcharge))"),
        ("n_low_peaks", 2, "Number of daily low-price peaks"),
        ("n_high_peaks", 2, "Number of daily high-price peaks"),
        ("window_size_hours_low", 4.0, "Half-window length (hours) for low peaks"),
        ("window_size_hours_high", 4.0, "Half-window length (hours) for high peaks"),
        ("time_window_start_hour", None, "Optional hour filter start (0–23); leave empty for auto"),
        ("time_window_end_hour", None, "Optional hour filter end (0–23); leave empty for auto"),
        ("use_reference_day", True, "Apply previous business day's peaks to the current day"),
    ],
    "quantile_daily_budget": [
        ("base_fee", 12.0, "Normal (ST) grid fee"),
        ("relative_fee_reduction", 0.4, "Discount factor in low windows"),
        ("relative_fee_surcharge", 0.2, "Surcharge factor in high windows"),
        ("q_low", 0.15, "Daily share of timesteps for low windows (0–1)"),
        ("q_high", 0.15, "Daily share of timesteps for high windows (0–1)"),
        ("selection_mode", "distributed", "Window selection: distributed or contiguous"),
        ("max_blocks_low", 2, "Max contiguous blocks for low windows"),
        ("max_blocks_high", 2, "Max contiguous blocks for high windows"),
        ("min_block_hours", 1.0, "Minimum block length in contiguous mode (hours)"),
    ],
    "load_linear_daily": [
        ("p_min", 10.0, "Minimum daily grid fee"),
        ("p_max", 30.0, "Maximum daily grid fee"),
    ],
    "subscription_capacity": [
        ("tier_caps_kw", "3.6,7,11", "Subscribed power caps per tier (kW), comma-separated"),
        ("tier_fees", "10,20,30", "Base fee per tier, comma-separated"),
        ("subscribed_tier_index", 2, "1-based index into the tier lists"),
        ("penalty_add", 1.5, "Linear penalty rate per kW overage (metadata only)"),
    ],
}


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)

    for sheet_name, rows in SHEET_ROWS.items():
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append(["parameter", "value", "description"])
        for parameter, value, description in rows:
            sheet.append([parameter, value, description])

    workbook.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
