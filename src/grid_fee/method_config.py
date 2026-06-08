from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

import pandas as pd

METHOD_SHEET_NAMES: tuple[str, ...] = (
    "topn_peak_reference_day",
    "quantile_daily_budget",
    "load_linear_daily",
    "subscription_capacity",
)

MethodsConfig: TypeAlias = dict[str, dict[str, object]]

_INT_PARAMS = frozenset(
    {
        "n_low_peaks",
        "n_high_peaks",
        "max_blocks_low",
        "max_blocks_high",
        "subscribed_tier_index",
        "time_window_start_hour",
        "time_window_end_hour",
    }
)
_BOOL_PARAMS = frozenset({"use_reference_day"})
_STR_PARAMS = frozenset({"selection_mode"})
_TIER_PARAMS = frozenset({"tier_caps_kw", "tier_fees"})


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _coerce_param_value(name: str, value: object) -> object:
    if name in _TIER_PARAMS:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value
    if name in _BOOL_PARAMS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return bool(int(value))
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        return bool(value)
    if name in _STR_PARAMS:
        return str(value).strip()
    if name in _INT_PARAMS:
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (
            stripped.startswith("-") and stripped[1:].replace(".", "", 1).isdigit()
        ):
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        return stripped
    return value


def _parse_params_sheet(df: pd.DataFrame) -> dict[str, object]:
    if "parameter" not in df.columns or "value" not in df.columns:
        raise ValueError(
            "Each method sheet must have 'parameter' and 'value' columns."
        )

    params: dict[str, object] = {}
    for _, row in df.iterrows():
        raw_name = row["parameter"]
        if _is_empty(raw_name):
            continue
        name = str(raw_name).strip()
        if not name or name.startswith("#"):
            continue
        value = row["value"]
        if _is_empty(value):
            continue
        params[name] = _coerce_param_value(name, value)
    return params


def load_methods_config_from_excel(path: str | Path) -> MethodsConfig:
    """
    Load method parameters from an Excel workbook with one sheet per method.

    Each sheet uses columns ``parameter``, ``value``, and optional ``description``.
    Empty value cells are omitted so registry defaults apply.
    """
    profile_path = Path(path)
    if not profile_path.is_file():
        raise FileNotFoundError(f"Method config workbook not found: {profile_path}")

    with pd.ExcelFile(profile_path) as workbook:
        missing = [name for name in METHOD_SHEET_NAMES if name not in workbook.sheet_names]
        if missing:
            missing_repr = ", ".join(missing)
            raise ValueError(
                f"Method config workbook is missing sheet(s): {missing_repr}."
            )
        return {
            sheet_name: _parse_params_sheet(pd.read_excel(workbook, sheet_name=sheet_name))
            for sheet_name in METHOD_SHEET_NAMES
        }
