"""A6: M3 attribution contract.

Usage is computed by zeroing PM k's rows of w* without re-solving; solo margin
keeps only that PM's rows at w* (C4). The residual is R = M - sum(u), and each
PM receives share = solo / sum(solo), with charge = (u + share*R) *
pass_through_bps * 1e-4 * H/360. Results contain one row per requested PM,
sorted by pm_id; credits are allowed. Row-order comparisons use tolerances
because NumPy summation order can move real-book usage by up to 4.8e-7 USD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.attribution import attribute, attribute_pm_usage
from mfl.margin import total_margin, validate_rates
from mfl.optimise import optimise
from tests.acceptance.test_a1_hand_worked import _market, _margin_subset
from tests.acceptance.test_a5_constraints import PARAMS, _load_real_case


def _charge_params(params):
    result = dict(params)
    result["horizon_days"] = float(result.get("horizon_days", 90.0))
    result["pass_through_bps"] = 100.0
    return result


def _case_b_allocation() -> np.ndarray:
    return np.array(
        [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]],
        dtype=float,
    )


@pytest.fixture(scope="module")
def real_case(data_raw):
    book, rates, providers, borrow, _ = _load_real_case(data_raw)
    params = dict(PARAMS)
    params["pass_through_bps"] = 100.0
    result = optimise(book, rates, providers, borrow, params)
    assert result.status == "optimal"
    pm_ids = pd.read_csv(data_raw / "pms.csv")["pm_id"].tolist()
    attributed = attribute(book, result.w, rates, providers, params, pm_ids=pm_ids)
    return book, rates, providers, borrow, params, result, pm_ids, attributed


@pytest.mark.parametrize(
    ("case", "allocation", "expected_usage", "expected_solo", "expected_charge"),
    [
        pytest.param(
            "a",
            np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]),
            {"A": 1_386_900.0, "B": -269_100.0},
            {"A": 3_622_500.0, "B": 1_966_500.0},
            {"A": 7_089.75, "B": 1_293.75},
            id="all-at-X",
        ),
        pytest.param(
            "b",
            _case_b_allocation(),
            {"A": 3_519_000.0, "B": 2_235_600.0},
            {"A": 3_622_500.0, "B": 2_339_100.0},
            {"A": 8_954.73, "B": 5_690.52},
            id="long-at-X-shorts-and-bond-at-Y",
        ),
    ],
)
def test_a6a_hand_worked_adds_up(case, allocation, expected_usage, expected_solo, expected_charge):
    book, rates, providers, raw_params = _market()
    params = _charge_params(raw_params)
    result = attribute(book, allocation, rates, providers, params, pm_ids=["A", "B"])
    full_margin = total_margin(book, allocation, rates, providers, params)
    actual = result.set_index("pm_id")

    assert abs(float(result["attributed_margin_usd"].sum()) - full_margin) <= 1e-6
    assert actual["usage_usd"].to_dict() == pytest.approx(expected_usage, abs=0.005)
    assert actual["solo_margin_usd"].to_dict() == pytest.approx(expected_solo, abs=0.005)
    assert actual["charge_usd"].to_dict() == pytest.approx(expected_charge, abs=0.005)


def test_a6a_real_book_adds_up(real_case):
    _, _, _, _, params, result, _, attributed = real_case
    total = float(result.margin_by_pb["margin_usd"].sum())
    pass_through_scale = params["pass_through_bps"] * 1e-4 * params["horizon_days"] / 360.0
    assert abs(float(attributed["attributed_margin_usd"].sum()) - total) <= 1e-6
    assert abs(float(attributed["charge_usd"].sum()) - total * pass_through_scale) <= 1e-6


def test_a6a_zeroing_equals_removal(real_case):
    book, rates, providers, _, params, result, pm_ids, attributed = real_case
    full_margin = float(result.margin_by_pb["margin_usd"].sum())
    actual_usage = attributed.set_index("pm_id")["usage_usd"]
    for pm_id in pm_ids:
        is_pm = book["pm_id"].eq(pm_id).to_numpy()
        remaining_margin = _margin_subset(
            book, result.w, ~is_pm, rates, providers, params
        )
        assert actual_usage[pm_id] == pytest.approx(full_margin - remaining_margin, abs=1e-6)


def test_a6b_pm_order(real_case):
    book, rates, providers, _, params, result, pm_ids, first = real_case
    reversed_result = attribute(
        book,
        result.w,
        rates,
        providers,
        params,
        pm_ids=list(reversed(pm_ids)),
    )
    pd.testing.assert_frame_equal(first, reversed_result)


def test_a6b_row_order(real_case):
    book, rates, providers, _, params, result, pm_ids, baseline = real_case
    baseline = baseline.set_index("pm_id").sort_index()
    total = float(result.margin_by_pb["margin_usd"].sum())
    usage_tol = 1e-12 * total
    rng = np.random.default_rng(42)
    for _ in range(5):
        permutation = rng.permutation(len(book))
        shuffled_book = book.iloc[permutation].reset_index(drop=True)
        shuffled_weights = result.w[permutation, :]
        shuffled = attribute(
            shuffled_book,
            shuffled_weights,
            rates,
            providers,
            params,
            pm_ids=pm_ids,
        ).set_index("pm_id").sort_index()
        for column, tolerance in (
            ("usage_usd", usage_tol),
            ("solo_margin_usd", usage_tol),
            ("charge_usd", 1e-6),
        ):
            assert np.all(
                np.abs(shuffled[column].to_numpy() - baseline[column].to_numpy()) <= tolerance
            )


def test_a6c_empty_book():
    book, rates, providers, raw_params = _market()
    params = _charge_params(raw_params)
    empty_book = book.iloc[:0].copy()
    result = attribute(
        empty_book,
        np.zeros((0, len(providers))),
        rates,
        providers,
        params,
        pm_ids=["A", "B"],
    )
    assert result["usage_usd"].tolist() == [0.0, 0.0]
    assert result["share"].tolist() == [0.0, 0.0]
    assert result["charge_usd"].tolist() == [0.0, 0.0]


def test_a6c_pm_without_positions():
    book, rates, providers, raw_params = _market()
    params = _charge_params(raw_params)
    allocation = _case_b_allocation()
    two_pm = attribute(book, allocation, rates, providers, params, pm_ids=["A", "B"])
    three_pm = attribute(book, allocation, rates, providers, params, pm_ids=["A", "B", "C"])

    actual = three_pm.set_index("pm_id")
    assert actual.loc["C", "usage_usd"] == 0.0
    assert actual.loc["C", "share"] == 0.0
    assert actual.loc["C", "charge_usd"] == 0.0
    pd.testing.assert_frame_equal(
        two_pm.set_index("pm_id").sort_index(),
        actual.loc[["A", "B"]].sort_index(),
    )


def test_a6c_zero_denominator_with_margin_raises():
    with pytest.raises(ValueError):
        attribute_pm_usage(
            usage={"A": 0.0},
            solo_margin={"A": 0.0},
            total_margin=1.0,
            pass_through_bps=100.0,
            horizon_days=90,
        )


@pytest.mark.parametrize(("column", "value"), [("base_rate", 0.0), ("phi", 1.0)])
def test_a6c_rates_file_rejected(data_raw, tmp_path, column, value):
    rates_path = data_raw / "pb_rates.csv"
    rates = pd.read_csv(rates_path)
    validate_rates(rates)

    rates.loc[0, column] = value
    altered_path = tmp_path / "pb_rates.csv"
    rates.to_csv(altered_path, index=False)
    altered_rates = pd.read_csv(altered_path)
    with pytest.raises(ValueError):
        validate_rates(altered_rates)
