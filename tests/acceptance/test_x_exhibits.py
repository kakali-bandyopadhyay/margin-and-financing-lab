"""X1–X3: separately reported re-solve, all-in cost, and Euler exhibits.

Euler totals equal M at kinks for this convex degree-one homogeneous margin
proxy; kinks make the PM split non-unique, so per-PM low/high bounds are
reported. Row-order checks use tolerances for floating-point summation drift.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.attribution import attribute
from mfl.exhibits import all_in_cost, euler_allocation, resolve_usage
from mfl.margin import build_index, margin_by_pb, total_margin
from mfl.optimise import funding_rates, optimise
from tests.acceptance.test_a1_hand_worked import _market
from tests.acceptance.test_a5_constraints import PARAMS, _load_real_case


RESOLVE_DELTA_OBJECTIVE = {
    "PM01": 7_772_005.04,
    "PM02": 1_747_743.41,
    "PM03": 1_725_516.79,
    "PM04": 806_777.31,
    "PM05": 7_483_428.51,
    "PM06": 1_572_588.22,
    "PM07": 302_581.35,
    "PM08": 152_356.75,
    "PM09": 368_405.53,
    "PM10": 151_267.12,
}

ALL_IN_REFERENCE = {
    "PM01": 7_854_480.63,
    "PM02": 1_646_630.84,
    "PM03": 1_661_934.59,
    "PM04": 840_408.77,
    "PM05": 7_091_032.82,
    "PM06": 1_608_334.92,
    "PM07": 296_887.56,
    "PM08": 154_697.97,
    "PM09": 392_881.86,
    "PM10": 167_047.29,
}


@pytest.fixture(scope="module")
def real_case(data_raw):
    book, rates, providers, borrow, _ = _load_real_case(data_raw)
    params = dict(PARAMS)
    params["pass_through_bps"] = 100.0
    base = optimise(book, rates, providers, borrow, params)
    assert base.status == "optimal"
    pm_ids = pd.read_csv(data_raw / "pms.csv")["pm_id"].tolist()
    attributed = attribute(book, base.w, rates, providers, params, pm_ids=pm_ids)
    return book, rates, providers, borrow, params, base, pm_ids, attributed


def _fixed_allocation_feasible(book, w, rates, borrow, providers, params) -> bool:
    pb_ids = tuple(providers["pb_id"].tolist())
    weights = np.asarray(w, dtype=float)
    notionals = book["notional_usd"].to_numpy(dtype=float)
    gross = notionals @ weights
    if np.any(gross - providers["capacity_usd"].to_numpy(dtype=float) > 1e-6):
        return False
    margins = margin_by_pb(book, weights, rates, providers, params)
    if np.any(
        margins["margin_usd"].to_numpy(dtype=float)
        - providers["counterparty_limit_usd"].to_numpy(dtype=float)
        > 1e-6
    ):
        return False

    _, allowed = funding_rates(book, rates, borrow, pb_ids)
    if np.any(np.abs(weights[~allowed]) > 1e-9):
        return False
    locate = book["needs_locate"].astype("boolean").fillna(False).to_numpy(dtype=bool)
    short_rows = (book["side"].to_numpy(dtype=float) < 0) & locate
    short_rows &= book["issuer_id"].notna().to_numpy()
    borrow_available = borrow.set_index(["pb_id", "issuer_id"])["borrow_available_usd"].to_dict()
    for col, pb_id in enumerate(pb_ids):
        for issuer_id, group in book.loc[short_rows].groupby("issuer_id", sort=False):
            rows = group.index.to_numpy(dtype=int)
            available = float(borrow_available.get((pb_id, issuer_id), 0.0))
            used = float(np.dot(notionals[rows], weights[rows, col]))
            if used > available + 1e-6:
                return False
    return True


def _allocation_objective(book, w, rates, borrow, providers, params) -> float:
    pb_ids = tuple(providers["pb_id"].tolist())
    k, allowed = funding_rates(book, rates, borrow, pb_ids)
    weights = np.asarray(w, dtype=float)
    if np.any(np.abs(weights[~allowed]) > 1e-9):
        return float("inf")
    horizon = float(params["horizon_days"])
    financing = float(
        np.sum(book["notional_usd"].to_numpy(dtype=float)[:, None] * weights * k)
        * 1e-4
        * horizon
        / 360.0
    )
    margin = total_margin(book, weights, rates, providers, params)
    margin_funding = (
        margin
        * float(params["liquidity_premium_bps"])
        * 1e-4
        * horizon
        / 360.0
    )
    return financing + margin_funding


def test_x1a_resolve_usage_recomputes_margins(real_case):
    book, rates, providers, borrow, params, base, pm_ids, _ = real_case
    result = resolve_usage(book, rates, providers, borrow, params, base)
    assert result["pm_id"].tolist() == sorted(pm_ids)
    assert result["status"].eq("optimal").all()

    full_margin = float(base.margin_by_pb["margin_usd"].sum())
    result_by_pm = result.set_index("pm_id")
    for pm_id in pm_ids:
        remaining = book.loc[book["pm_id"].ne(pm_id)].reset_index(drop=True)
        resolved = optimise(remaining, rates, providers, borrow, params)
        assert resolved.status == "optimal"
        remaining_margin = total_margin(
            remaining, resolved.w, rates, providers, params
        )
        assert result_by_pm.loc[pm_id, "margin_without_usd"] == pytest.approx(
            remaining_margin, abs=1e-6
        )
        assert result_by_pm.loc[pm_id, "usage_resolve_usd"] == pytest.approx(
            full_margin - remaining_margin, abs=1e-6
        )


def test_x1b_resolve_objective_is_no_worse_than_feasible_deletion(real_case):
    book, rates, providers, borrow, params, base, pm_ids, _ = real_case
    result = resolve_usage(book, rates, providers, borrow, params, base).set_index("pm_id")
    objective_tolerance = 1e-6 * base.objective_usd
    for pm_id in pm_ids:
        rows = book["pm_id"].eq(pm_id).to_numpy()
        remaining = book.loc[~rows].reset_index(drop=True)
        fixed_weights = base.w[~rows, :]
        if not _fixed_allocation_feasible(
            remaining, fixed_weights, rates, borrow, providers, params
        ):
            continue
        fixed_objective = _allocation_objective(
            remaining, fixed_weights, rates, borrow, providers, params
        )
        assert result.loc[pm_id, "objective_without_usd"] <= fixed_objective + objective_tolerance


def test_x1c_resolve_objective_matches_reference(real_case):
    book, rates, providers, borrow, params, base, _, _ = real_case
    result = resolve_usage(book, rates, providers, borrow, params, base).set_index("pm_id")
    assert result["delta_objective_usd"].to_dict() == pytest.approx(
        RESOLVE_DELTA_OBJECTIVE, abs=1.00
    )


def test_x2a_all_in_cost_matches_reference(real_case):
    book, rates, providers, borrow, params, base, _, attributed = real_case
    result = all_in_cost(book, base.w, rates, borrow, providers, params, attributed)
    assert result["financing_usd"].sum() == pytest.approx(base.financing_usd, abs=1e-6)
    assert result["margin_funding_usd"].sum() == pytest.approx(
        base.margin_funding_usd, abs=1e-6
    )
    assert result["all_in_usd"].sum() == pytest.approx(base.objective_usd, abs=1e-6)
    assert result.set_index("pm_id")["all_in_usd"].to_dict() == pytest.approx(
        ALL_IN_REFERENCE, abs=0.01
    )


def test_x2b_margin_funding_is_separate_from_pass_through(real_case):
    book, rates, providers, borrow, params, base, pm_ids, attributed_100 = real_case
    result_100 = all_in_cost(book, base.w, rates, borrow, providers, params, attributed_100)
    params_50 = dict(params)
    params_50["pass_through_bps"] = 50.0
    attributed_50 = attribute(book, base.w, rates, providers, params_50, pm_ids=pm_ids)
    result_50 = all_in_cost(book, base.w, rates, borrow, providers, params_50, attributed_50)

    np.testing.assert_allclose(
        result_50["margin_funding_usd"], result_100["margin_funding_usd"], atol=1e-6, rtol=0.0
    )
    np.testing.assert_allclose(
        attributed_50["charge_usd"], attributed_100["charge_usd"] / 2.0, atol=1e-6, rtol=0.0
    )
    assert not np.allclose(
        result_50["margin_funding_usd"], attributed_50["charge_usd"], atol=1e-6, rtol=0.0
    )


def test_x3a_euler_hand_case_a():
    book, rates, providers, params = _market()
    weights = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
    per_pm, kinks = euler_allocation(book, weights, rates, providers, params, pm_ids=["A", "B"])
    actual = per_pm.set_index("pm_id")
    assert actual["euler_usd"].to_dict() == pytest.approx(
        {"A": 3_622_500.0, "B": -269_100.0}, abs=0.005
    )
    assert kinks.empty
    assert actual["euler_low_usd"].to_dict() == pytest.approx(actual["euler_usd"].to_dict())
    assert actual["euler_high_usd"].to_dict() == pytest.approx(actual["euler_usd"].to_dict())


def test_x3b_euler_hand_case_b():
    book, rates, providers, params = _market()
    weights = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]])
    per_pm, kinks = euler_allocation(book, weights, rates, providers, params, pm_ids=["A", "B"])
    assert per_pm.set_index("pm_id")["euler_usd"].to_dict() == pytest.approx(
        {"A": 3_622_500.0, "B": 2_235_600.0}, abs=0.005
    )
    assert kinks.empty


def test_x3c_euler_net_kink_ranges():
    book, rates, providers, params = _market()
    book = book.iloc[:2].copy().reset_index(drop=True)
    book.loc[1, "notional_usd"] = 10_000_000.0
    weights = np.array([[1.0, 0.0], [1.0, 0.0]])
    per_pm, kinks = euler_allocation(book, weights, rates, providers, params)
    actual = per_pm.set_index("pm_id")
    assert len(kinks) == 1
    assert kinks.iloc[0]["kind"] == "net"
    assert actual["euler_usd"].to_dict() == pytest.approx(
        {"A": 1_414_500.0, "B": 1_414_500.0}, abs=0.005
    )
    assert actual["euler_low_usd"].to_dict() == pytest.approx(
        {"A": -448_500.0, "B": -448_500.0}, abs=0.005
    )
    assert actual["euler_high_usd"].to_dict() == pytest.approx(
        {"A": 3_277_500.0, "B": 3_277_500.0}, abs=0.005
    )
    assert per_pm["euler_usd"].sum() == pytest.approx(2_829_000.0, abs=0.005)


def test_x3d_euler_concentration_hinge_kink_ranges():
    book, rates, providers, params = _market()
    book = book.iloc[[0, 2]].copy().reset_index(drop=True)
    book.loc[1, "notional_usd"] = 30_000_000.0
    book.loc[1, "pm_id"] = "B"
    weights = np.array([[1.0, 0.0], [1.0, 0.0]])
    per_pm, kinks = euler_allocation(book, weights, rates, providers, params)
    actual = per_pm.set_index("pm_id")
    assert len(kinks) == 1
    assert kinks.iloc[0]["kind"] == "hinge"
    assert total_margin(book, weights, rates, providers, params) == pytest.approx(
        3_795_000.0, abs=0.005
    )
    assert actual["euler_usd"].to_dict() == pytest.approx(
        {"A": 3_105_000.0, "B": 690_000.0}, abs=0.005
    )
    assert actual["euler_low_usd"].to_dict() == pytest.approx(
        {"A": 3_105_000.0, "B": 517_500.0}, abs=0.005
    )
    assert actual["euler_high_usd"].to_dict() == pytest.approx(
        {"A": 3_277_500.0, "B": 690_000.0}, abs=0.005
    )


def test_x3e_real_book_euler_total_kinks_and_sandwich(real_case):
    book, rates, providers, _, params, base, pm_ids, attributed = real_case
    per_pm, kinks = euler_allocation(book, base.w, rates, providers, params, pm_ids=pm_ids)
    total = float(base.margin_by_pb["margin_usd"].sum())
    assert abs(float(per_pm["euler_usd"].sum()) - total) <= 1e-6 * total
    assert not kinks.empty
    assert set(kinks["kind"]).issubset({"net", "hinge"})

    actual = per_pm.set_index("pm_id")
    usage = attributed.set_index("pm_id")["usage_usd"]
    solo = attributed.set_index("pm_id")["solo_margin_usd"]
    tolerance = 1e-6
    assert np.all(usage.loc[actual.index].to_numpy() <= actual["euler_low_usd"].to_numpy() + tolerance)
    assert np.all(actual["euler_low_usd"].to_numpy() <= actual["euler_usd"].to_numpy() + tolerance)
    assert np.all(actual["euler_usd"].to_numpy() <= actual["euler_high_usd"].to_numpy() + tolerance)
    assert np.all(actual["euler_high_usd"].to_numpy() <= solo.loc[actual.index].to_numpy() + tolerance)


@pytest.mark.parametrize("scale", [0.5, 2.0])
def test_x3f_euler_is_homogeneous_in_notional(real_case, scale):
    book, rates, providers, _, params, base, pm_ids, _ = real_case
    index = build_index(book, providers, rates, params["vol_multipliers"])
    original, _ = euler_allocation(
        book, base.w, rates, providers, params, pm_ids=pm_ids, index=index
    )
    scaled_book = book.copy()
    scaled_book["notional_usd"] *= scale
    scaled, _ = euler_allocation(
        scaled_book, base.w, rates, providers, params, pm_ids=pm_ids, index=index
    )
    margin_total = float(base.margin_by_pb["margin_usd"].sum())
    np.testing.assert_allclose(
        scaled["euler_usd"].to_numpy(dtype=float),
        scale * original["euler_usd"].to_numpy(dtype=float),
        atol=1e-9 * margin_total,
        rtol=0.0,
    )
