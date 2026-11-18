from __future__ import annotations

import shutil

import pandas as pd
import pytest

from mfl.io import load_case
from tests.acceptance.test_a5_constraints import PARAMS, _load_real_case


def test_p1_loader_matches_acceptance(data_raw):
    expected = _load_real_case(data_raw)
    actual = load_case(data_raw)
    for got, wanted in zip((actual.book, actual.rates, actual.providers, actual.borrow), expected[:4], strict=True):
        pd.testing.assert_frame_equal(got, wanted)
    for key, value in PARAMS.items():
        expected_value = actual.params[key]
        if isinstance(value, dict):
            assert expected_value == value
        else:
            assert expected_value == value


@pytest.mark.parametrize(("column", "value"), [("base_rate", 0.0), ("phi", 1.0)])
def test_p2_invalid_rates_fail_during_load(data_raw, tmp_path, column, value):
    target = tmp_path / "raw"
    shutil.copytree(data_raw, target)
    rates = pd.read_csv(target / "pb_rates.csv")
    rates.loc[0, column] = value
    rates.to_csv(target / "pb_rates.csv", index=False)
    with pytest.raises(ValueError):
        load_case(target)


def test_p3_phi_mismatch_names_params(data_raw, tmp_path):
    target = tmp_path / "raw"
    shutil.copytree(data_raw, target)
    params = pd.read_csv(target / "params.csv")
    params.loc[params["name"].eq("phi"), "value"] = "0.61"
    params.to_csv(target / "params.csv", index=False)
    with pytest.raises(ValueError, match="params.csv"):
        load_case(target)
