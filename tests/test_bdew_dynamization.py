from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from grid_fee.bdew_dynamization import (
    bdew_dynamization_factor,
    load_dynamization_mapping,
    profile_requires_dynamization,
)
from grid_fee.bdew_profiles import (
    BdewProfileTable,
    build_bdew_weights_for_timestamps,
    classify_bdew_day_type,
    get_bdew_profile,
    load_bdew_profile_xlsx,
)

BDEW_XLSX = Path(__file__).resolve().parents[1] / "profile_bdew.xlsx"
has_bdew = BDEW_XLSX.is_file()


def test_bdew_dynamization_factor_reference_values():
    assert bdew_dynamization_factor(202) == 0.7847
    assert bdew_dynamization_factor(365) == 1.2572
    assert bdew_dynamization_factor(366) == 1.2597


def test_profile_requires_dynamization_defaults():
    assert profile_requires_dynamization("H25", "H25", {}) is True
    assert profile_requires_dynamization("P25", "P25", {}) is True
    assert profile_requires_dynamization("S25", "S25", {}) is True
    assert profile_requires_dynamization("G25", "G25", {}) is False
    assert profile_requires_dynamization("L25", "L25", {}) is False


def test_profile_requires_dynamization_sheet_overrides_defaults():
    mapping = {"H25": False, "G25": True}
    assert profile_requires_dynamization("H25", "H25", mapping) is False
    assert profile_requires_dynamization("G25", "G25", mapping) is True


def test_load_dynamization_mapping_from_temp_workbook(tmp_path):
    path = tmp_path / "profiles.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet(title="Dynamisierung")
    sheet.append(["Dynamisches Profil", None, None, "Dynamisierungsfunktion"])
    sheet.append(["H25", None, None, "standard"])
    sheet.append(["G25", None, None, None])
    workbook.save(path)

    mapping = load_dynamization_mapping(str(path))
    assert mapping == {"H25": True, "G25": False}


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_load_bdew_profile_h25_requires_dynamization():
    profile = load_bdew_profile_xlsx(BDEW_XLSX, sheet_name="H25")
    assert profile.requires_dynamization is True


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_load_bdew_profile_g25_skips_dynamization():
    profile = load_bdew_profile_xlsx(BDEW_XLSX, sheet_name="G25")
    assert profile.requires_dynamization is False


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_dynamized_weights_scale_by_day_factor():
    profile = get_bdew_profile(BDEW_XLSX, sheet_name="H25")
    ts = pd.Timestamp("2024-07-20 00:00:00", tz="Europe/Berlin")  # day 202 in leap year
    weights = build_bdew_weights_for_timestamps(pd.Series([ts]), profile)
    raw = profile.weight(7, classify_bdew_day_type(ts), 0)
    assert weights.iloc[0] == pytest.approx(raw * bdew_dynamization_factor(202))


@pytest.mark.skipif(not has_bdew, reason="profile_bdew.xlsx required")
def test_g25_weights_ignore_dynamization_factor():
    profile = get_bdew_profile(BDEW_XLSX, sheet_name="G25")
    ts = pd.Timestamp("2026-07-20 00:00:00", tz="Europe/Berlin")
    weights = build_bdew_weights_for_timestamps(pd.Series([ts]), profile)
    raw = profile.weight(7, classify_bdew_day_type(ts), 0)
    assert weights.iloc[0] == pytest.approx(raw)


def test_build_weights_without_dynamization_flag():
    profile = BdewProfileTable(
        profile_code="TEST",
        values=tuple(
            tuple(tuple([1.0] * 96 for _ in range(3)) for _ in range(12))
        ),
        requires_dynamization=False,
    )
    ts = pd.Timestamp("2026-07-20 12:00:00", tz="UTC")
    weights = build_bdew_weights_for_timestamps(pd.Series([ts]), profile)
    assert weights.iloc[0] == 1.0
