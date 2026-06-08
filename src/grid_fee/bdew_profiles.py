from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd

from grid_fee.bdew_dynamization import (
    bdew_dynamization_factor,
    load_dynamization_mapping,
    profile_requires_dynamization,
)

DayType = Literal["SA", "FT", "WT"]
DAY_TYPE_ORDER: tuple[DayType, ...] = ("SA", "FT", "WT")
SLOTS_PER_DAY = 96
DATA_START_ROW = 4
HEADER_MONTH_ROW = 2
HEADER_DAYTYPE_ROW = 3
FIRST_DATA_COL = 2


@dataclass(frozen=True)
class BdewProfileTable:
    """BDEW standard load profile: kWh per 15 min per 1e6 kWh/a, by month and day type."""

    profile_code: str
    values: tuple[tuple[tuple[float, ...], ...], ...]  # [month 0..11][day_type 0..2][slot 0..95]
    requires_dynamization: bool = False

    def weight(self, month: int, day_type: DayType, slot: int) -> float:
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1..12, got {month}")
        if not 0 <= slot < SLOTS_PER_DAY:
            raise ValueError(f"slot must be 0..{SLOTS_PER_DAY - 1}, got {slot}")
        dt_idx = DAY_TYPE_ORDER.index(day_type)
        return self.values[month - 1][dt_idx][slot]


def default_bdew_profile_path() -> Path:
    """Resolve ``profile_bdew.xlsx`` from cwd or repository root."""
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "profile_bdew.xlsx",
        here.parents[2] / "profile_bdew.xlsx",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "profile_bdew.xlsx not found. Place the BDEW profile workbook in the "
        "project root or set bdew_profile_path explicitly."
    )


def classify_bdew_day_type(ts: pd.Timestamp) -> DayType:
    """
    Map a timestamp to BDEW day type (SA / FT / WT).

    Uses Europe/Berlin calendar: Saturday → SA, Sunday → FT, Monday–Friday → WT.
    Public holidays on weekdays are not classified as FT unless you extend this helper.
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("Europe/Berlin")
    weekday = t.weekday()
    if weekday == 5:
        return "SA"
    if weekday == 6:
        return "FT"
    return "WT"


def _parse_time_slot_label(label: object) -> int:
    text = str(label).strip()
    if "-" not in text:
        raise ValueError(f"Unexpected time slot label: {label!r}")
    start = text.split("-", 1)[0].strip()
    hour, minute = (int(part) for part in start.split(":"))
    return (hour * 60 + minute) // 15


def load_bdew_profile_xlsx(
    path: str | Path | None = None,
    *,
    sheet_name: str = "H25",
) -> BdewProfileTable:
    """
    Load a BDEW profile sheet from ``profile_bdew.xlsx``.

    Default sheet ``H25`` is the household (Haushalt) profile. Other sheets:
    ``G25``, ``L25``, ``P25``, ``S25``.
    """
    profile_path = Path(path) if path is not None else default_bdew_profile_path()
    raw = pd.read_excel(profile_path, sheet_name=sheet_name, header=None)

    profile_code = str(raw.iloc[0, 2]).strip() if pd.notna(raw.iloc[0, 2]) else sheet_name
    n_cols = raw.shape[1] - FIRST_DATA_COL
    if n_cols != 36:
        raise ValueError(
            f"Expected 36 data columns (12 months x 3 day types), got {n_cols}."
        )

    month_headers = raw.iloc[HEADER_MONTH_ROW, FIRST_DATA_COL:].tolist()
    daytype_headers = raw.iloc[HEADER_DAYTYPE_ROW, FIRST_DATA_COL:].tolist()

    columns: list[tuple[int, DayType, int]] = []
    for col_idx, (month_val, day_val) in enumerate(zip(month_headers, daytype_headers)):
        month = pd.Timestamp(month_val).month
        day_type = str(day_val).strip()
        if day_type not in DAY_TYPE_ORDER:
            raise ValueError(f"Unknown day type {day_type!r} in column {col_idx}.")
        columns.append((month, day_type, col_idx + FIRST_DATA_COL))

    slot_rows: dict[int, dict[tuple[int, DayType], float]] = {}
    for row_idx in range(DATA_START_ROW, raw.shape[0]):
        slot = _parse_time_slot_label(raw.iloc[row_idx, 1])
        if slot in slot_rows:
            raise ValueError(f"Duplicate slot index {slot} in profile sheet.")
        slot_rows[slot] = {}
        for month, day_type, col in columns:
            value = float(pd.to_numeric(raw.iloc[row_idx, col], errors="coerce"))
            slot_rows[slot][(month, day_type)] = value

    if len(slot_rows) != SLOTS_PER_DAY:
        raise ValueError(f"Expected {SLOTS_PER_DAY} time slots, got {len(slot_rows)}.")

    values: list[list[list[float]]] = [[[] for _ in range(3)] for _ in range(12)]
    for month in range(1, 13):
        for day_type in DAY_TYPE_ORDER:
            series = [
                slot_rows[slot][(month, day_type)]
                for slot in range(SLOTS_PER_DAY)
            ]
            values[month - 1][DAY_TYPE_ORDER.index(day_type)] = series

    nested = tuple(
        tuple(tuple(month_row) for month_row in month_block) for month_block in values
    )
    dynamization_mapping = load_dynamization_mapping(str(profile_path))
    requires_dynamization = profile_requires_dynamization(
        profile_code,
        sheet_name,
        dynamization_mapping,
    )
    return BdewProfileTable(
        profile_code=profile_code,
        values=nested,
        requires_dynamization=requires_dynamization,
    )


@lru_cache(maxsize=8)
def _cached_bdew_table(path_str: str, sheet_name: str) -> BdewProfileTable:
    return load_bdew_profile_xlsx(path_str, sheet_name=sheet_name)


def get_bdew_profile(
    path: str | Path | None = None,
    *,
    sheet_name: str = "H25",
) -> BdewProfileTable:
    resolved = str(Path(path) if path is not None else default_bdew_profile_path())
    return _cached_bdew_table(resolved, sheet_name)


def _infer_step_minutes(timestamps: pd.Series) -> int:
    ts = pd.to_datetime(timestamps, utc=True).sort_values()
    if len(ts) < 2:
        return 15
    delta = ts.diff().dropna().median()
    minutes = int(round(delta.total_seconds() / 60.0))
    if minutes <= 0:
        return 15
    return minutes


def build_bdew_weights_for_timestamps(
    timestamps: pd.Series,
    profile: BdewProfileTable,
) -> pd.Series:
    """
    Build H0/SLP weights for each output timestamp using the BDEW 15-minute table.

    For entdynamisierte profiles (H25, P25, S25 by default), each weight is
    multiplied by the BDEW Dynamisierungsfaktor F_t for the calendar day.

    For steps longer than 15 minutes, sums the underlying quarter-hour weights
    for the half-open interval ``[t, t + step)``.
    """
    ts = pd.Series(pd.to_datetime(timestamps, utc=True)).reset_index(drop=True)
    step_min = _infer_step_minutes(ts)
    if step_min % 15 != 0:
        raise ValueError(
            f"Timestamp step must be a multiple of 15 minutes, got {step_min} min."
        )
    steps_per_slot = step_min // 15

    weights: list[float] = []
    for t in ts:
        t = pd.Timestamp(t)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        local = t.tz_convert("Europe/Berlin") if t.tzinfo is not None else t
        day_type = classify_bdew_day_type(t)
        month = local.month
        day_factor = (
            bdew_dynamization_factor(int(local.dayofyear))
            if profile.requires_dynamization
            else 1.0
        )
        start_slot = (local.hour * 60 + local.minute) // 15
        total = 0.0
        for offset in range(steps_per_slot):
            slot = start_slot + offset
            if slot >= SLOTS_PER_DAY:
                break
            total += profile.weight(month, day_type, slot) * day_factor
        weights.append(total)

    return pd.Series(weights, index=ts.index, dtype=float)
