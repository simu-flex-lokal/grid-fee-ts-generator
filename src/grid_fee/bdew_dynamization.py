from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

DYNAMIZATION_SHEET_NAME = "Dynamisierung"

# BDEW 2025: H25, P25, S25 are entdynamisiert; G25, L25 are not.
_DEFAULT_REQUIRES_DYNAMIZATION: dict[str, bool] = {
    "H25": True,
    "P25": True,
    "S25": True,
    "G25": False,
    "L25": False,
}


def bdew_dynamization_factor(day_of_year: int) -> float:
    """
    BDEW Dynamisierungsfaktor F_t for calendar day *t* (1 = 1 Jan, 365/366 = 31 Dec).

    Polynomial per BDEW "Anwendung repräsentativer Lastprofile – Step by step".
    Factors are rounded to four decimal places as recommended by BDEW.
    """
    if not 1 <= day_of_year <= 366:
        raise ValueError(f"day_of_year must be 1..366, got {day_of_year}")
    t = float(day_of_year)
    raw = (
        -3.92e-10 * t**4
        + 3.2e-7 * t**3
        - 7.02e-5 * t**2
        + 2.1e-3 * t
        + 1.24
    )
    return round(raw, 4)


def _normalize_profile_code(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "dynamisches profil":
        return None
    return text.upper()


@lru_cache(maxsize=4)
def load_dynamization_mapping(path_str: str) -> dict[str, bool]:
    """
    Read the ``Dynamisierung`` sheet: profile code → whether to apply F_t.

    A non-empty ``Dynamisierungsfunktion`` cell enables dynamization for that profile.
    When the sheet has no data rows, returns an empty dict and callers fall back to
    :data:`_DEFAULT_REQUIRES_DYNAMIZATION`.
    """
    path = Path(path_str)
    try:
        raw = pd.read_excel(path, sheet_name=DYNAMIZATION_SHEET_NAME, header=None)
    except ValueError:
        return {}

    mapping: dict[str, bool] = {}
    for row_idx in range(raw.shape[0]):
        profile_code = _normalize_profile_code(raw.iloc[row_idx, 0])
        if profile_code is None:
            continue
        func_cell = raw.iloc[row_idx, 3] if raw.shape[1] > 3 else None
        if func_cell is None or (isinstance(func_cell, float) and pd.isna(func_cell)):
            requires = False
        else:
            requires = bool(str(func_cell).strip())
        mapping[profile_code] = requires
    return mapping


def profile_requires_dynamization(
    profile_code: str,
    sheet_name: str,
    mapping: dict[str, bool],
) -> bool:
    """Resolve whether *profile_code* / *sheet_name* needs BDEW dynamization."""
    for key in (profile_code.upper(), sheet_name.upper()):
        if key in mapping:
            return mapping[key]
        if key in _DEFAULT_REQUIRES_DYNAMIZATION:
            return _DEFAULT_REQUIRES_DYNAMIZATION[key]
    return False
