from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfl.io import load_case
from tests.acceptance.test_a5_constraints import PARAMS, _load_real_case


def _copy_case(data_raw: Path, tmp_path: Path) -> Path:
    target = tmp_path / "raw"
    shutil.copytree(data_raw, target)
    shutil.copy2(data_raw.parent / "SOURCES.md", tmp_path / "SOURCES.md")
    return target


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
    target = _copy_case(data_raw, tmp_path)
    rates = pd.read_csv(target / "pb_rates.csv")
    rates.loc[0, column] = value
    rates.to_csv(target / "pb_rates.csv", index=False)
    with pytest.raises(ValueError):
        load_case(target)


@pytest.mark.parametrize(
    ("name", "value"),
    [("phi", "0.61"), ("conc_threshold", "0.24"), ("conc_rate", "0.03")],
)
def test_p3_parameter_mismatches_name_params(data_raw, tmp_path, name, value):
    target = _copy_case(data_raw, tmp_path)
    params = pd.read_csv(target / "params.csv")
    params.loc[params["name"].eq(name), "value"] = value
    params.to_csv(target / "params.csv", index=False)
    with pytest.raises(ValueError, match="params.csv"):
        load_case(target)


@pytest.mark.parametrize(
    ("filename", "column", "value", "message"),
    [
        ("providers.csv", "conc_threshold", 0.0, "conc_threshold"),
        ("providers.csv", "conc_threshold", 1.0, "conc_threshold"),
        ("providers.csv", "conc_rate", -0.01, "conc_rate"),
        ("params.csv", "liquidity_premium_bps", "-1", "liquidity_premium_bps"),
    ],
)
def test_p4_concentration_and_liquidity_bounds(data_raw, tmp_path, filename, column, value, message):
    target = _copy_case(data_raw, tmp_path)
    frame = pd.read_csv(target / filename)
    if filename == "params.csv":
        frame.loc[frame["name"].eq(column), "value"] = value
    else:
        frame.loc[0, column] = value
    frame.to_csv(target / filename, index=False)
    with pytest.raises(ValueError, match=message):
        load_case(target)


@pytest.mark.parametrize(
    ("filename", "selector", "column", "value", "message"),
    [
        ("products.csv", lambda df: df["product_type"].eq("fx_forward"), "issuer_id", "ISS001", "issuer_id"),
        ("products.csv", lambda df: df["product_type"].eq("irs_proxy_future"), "needs_locate", True, "needs_locate"),
        ("issuers.csv", lambda df: df["asset_class"].eq("rates"), "conc_eligible", True, "conc_eligible"),
        ("positions.csv", lambda df: pd.Series(True, index=df.index), "side", 0, "side"),
        ("positions.csv", lambda df: pd.Series(True, index=df.index), "notional_usd", 0, "notional_usd"),
    ],
)
def test_p5_product_issuer_locate_and_position_rules(
    data_raw, tmp_path, filename, selector, column, value, message
):
    target = _copy_case(data_raw, tmp_path)
    frame = pd.read_csv(target / filename)
    row = frame.loc[selector(frame)].index[0]
    frame.loc[row, column] = value
    frame.to_csv(target / filename, index=False)
    with pytest.raises(ValueError, match=message):
        load_case(target)


@pytest.mark.parametrize("duplicate", [False, True])
def test_p6_held_positions_need_one_rate_per_pb(data_raw, tmp_path, duplicate):
    target = _copy_case(data_raw, tmp_path)
    position = pd.read_csv(target / "positions.csv").iloc[0]
    rates = pd.read_csv(target / "pb_rates.csv")
    match = rates["pb_id"].eq("PB_A") & rates["product_id"].eq(position["product_id"]) & rates[
        "liquidity_tier"
    ].eq(position["liquidity_tier"])
    if duplicate:
        rates = pd.concat([rates, rates.loc[match]], ignore_index=True)
        expected = "duplicate"
    else:
        rates = rates.loc[~match]
        expected = "missing rates"
    rates.to_csv(target / "pb_rates.csv", index=False)
    with pytest.raises(ValueError, match=expected):
        load_case(target)


def test_p7_missing_history_for_held_product_fails(data_raw, tmp_path):
    target = _copy_case(data_raw, tmp_path)
    position = pd.read_csv(target / "positions.csv").iloc[0]
    prices = pd.read_csv(target / "price_history.csv")
    prices = prices.loc[~prices["product_id"].eq(position["product_id"])]
    prices.to_csv(target / "price_history.csv", index=False)
    with pytest.raises(ValueError, match="price history missing"):
        load_case(target)


def test_p8_missing_data_provenance_tag_fails(data_raw, tmp_path):
    target = _copy_case(data_raw, tmp_path)
    manifest = tmp_path / "SOURCES.md"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("| pms.csv |"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells[6] = ""
            lines[index] = "| " + " | ".join(cells) + " |"
            break
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance tag missing for pms.csv"):
        load_case(target)


def test_p9_missing_parameter_provenance_tag_fails(data_raw, tmp_path):
    target = _copy_case(data_raw, tmp_path)
    manifest = tmp_path / "SOURCES.md"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("| phi |"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells[2] = ""
            lines[index] = "| " + " | ".join(cells) + " |"
            break
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance tag missing for parameter phi"):
        load_case(target)
