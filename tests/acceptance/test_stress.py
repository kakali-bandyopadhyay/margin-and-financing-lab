"""S1–S7 and review-item tests for the Phase 2a static stress projection.

The tests follow ``prereg/PREREGISTRATION_PHASE2A.md``.  They are written by
the author, per the authorship rule in ``S1_GUIDE.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.io import load_case
from mfl.margin import margin_detail, vol_bucket
from mfl.stress import (
    SCENARIOS,
    annualised_vol,
    run_scenarios,
    scenario_inputs,
    stressed_vol_bucket,
    write_outputs,
)


AS_OF = "2026-10-30"


@pytest.fixture(scope="module")
def stress_case(data_raw):
    case = load_case(data_raw)
    prices = pd.read_csv(data_raw / "price_history.csv", parse_dates=["date"])
    result = run_scenarios(case, prices=prices)
    return case, prices, result


def _family_by_pb(case, weights, rates):
    family, _ = margin_detail(case.book, weights, rates, case.providers, case.params)
    return family.groupby("pb_id")["margin_usd"].sum()


def _addon_by_pb(case, weights, rates):
    _, issuer = margin_detail(case.book, weights, rates, case.providers, case.params)
    return issuer.groupby("pb_id")["addon_usd"].sum()


def _top_two(case, result):
    st0 = result.margin_by_pb[result.margin_by_pb["scenario"].eq("ST0")]
    values = dict(zip(st0["pb_id"], st0["margin_usd"], strict=True))
    order = {pb_id: index for index, pb_id in enumerate(case.providers["pb_id"])}
    return sorted(case.providers["pb_id"], key=lambda pb: (-values[pb], order[pb]))[:2]


def test_s1_st0_reproduces_run_42_to_the_cent(stress_case, repo_root):
    _, _, result = stress_case
    st0 = result.summary.set_index("scenario").loc["ST0"]
    run_42 = pd.read_csv(repo_root / "reports" / "run_42" / "results" / "run_summary.csv").iloc[0]

    assert st0["status"] == "optimal"
    for column, expected_column in (
        ("total_margin_usd", "total_margin_usd"),
        ("financing_cost_usd", "financing_usd"),
        ("margin_funding_cost_usd", "margin_funding_usd"),
    ):
        assert round(float(st0[column]), 2) == round(float(run_42[expected_column]), 2)
    objective = float(st0["financing_cost_usd"]) + float(st0["margin_funding_cost_usd"])
    assert round(objective, 2) == round(float(run_42["objective_usd"]), 2)


def test_s2_st1a_and_st1b_rebucket_hand_worked_products(stress_case):
    _, prices, _ = stress_case
    expected = {
        "CDS_ISS003": (0.090769468946, "V1", 0.181538937892, "V2", 0.136154203419, "V2"),
        "CE_ISS008": (0.193704438203, "V2", 0.387408876406, "V3", 0.290556657304, "V3"),
    }
    for product_id, (base_vol, base_bucket, x2_vol, x2_bucket, x15_vol, x15_bucket) in expected.items():
        closes = prices.loc[prices["product_id"].eq(product_id)].set_index("date")["close"]
        vol = annualised_vol(closes, AS_OF)
        assert vol is not None
        assert vol == pytest.approx(base_vol, rel=1e-12)
        assert stressed_vol_bucket(closes, AS_OF, 1.0) == base_bucket
        assert stressed_vol_bucket(closes, AS_OF, 2.0) == x2_bucket
        assert stressed_vol_bucket(closes, AS_OF, 1.5) == x15_bucket
        assert annualised_vol(closes, AS_OF) * 2.0 == pytest.approx(x2_vol, rel=1e-12)
        assert annualised_vol(closes, AS_OF) * 1.5 == pytest.approx(x15_vol, rel=1e-12)


def test_s3_st2a_scales_family_margin_but_not_addon_at_fixed_allocation(stress_case):
    case, _, result = stress_case
    w0 = result.weights["ST0"]
    rates_st2a = case.rates.copy()
    rates_st2a["base_rate"] = rates_st2a["base_rate"].astype(float) * 1.5

    family_st0 = _family_by_pb(case, w0, case.rates)
    family_st2a = _family_by_pb(case, w0, rates_st2a)
    np.testing.assert_allclose(
        family_st2a.to_numpy(dtype=float),
        1.5 * family_st0.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-6,
    )

    addon_st0 = _addon_by_pb(case, w0, case.rates)
    addon_st2a = _addon_by_pb(case, w0, rates_st2a)
    np.testing.assert_allclose(
        addon_st2a.to_numpy(dtype=float),
        addon_st0.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        rates_st2a["base_rate"].to_numpy(dtype=float),
        1.5 * case.rates["base_rate"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_array_equal(
        rates_st2a["financing_spread_bps"].to_numpy(dtype=float),
        case.rates["financing_spread_bps"].to_numpy(dtype=float),
    )


def test_s4_st2b_shocks_only_top_two_at_fixed_allocation(stress_case):
    case, _, result = stress_case
    w0 = result.weights["ST0"]
    top_two = _top_two(case, result)
    rates_st2b = case.rates.copy()
    shocked = rates_st2b["pb_id"].isin(top_two)
    rates_st2b.loc[shocked, "base_rate"] = (
        rates_st2b.loc[shocked, "base_rate"].astype(float) * 1.5
    )

    unshocked = ~case.rates["pb_id"].isin(top_two)
    np.testing.assert_array_equal(
        rates_st2b.loc[unshocked, "base_rate"].to_numpy(dtype=float),
        case.rates.loc[unshocked, "base_rate"].to_numpy(dtype=float),
    )
    np.testing.assert_allclose(
        rates_st2b.loc[shocked, "base_rate"].to_numpy(dtype=float),
        1.5 * case.rates.loc[shocked, "base_rate"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_array_equal(
        rates_st2b["financing_spread_bps"].to_numpy(dtype=float),
        case.rates["financing_spread_bps"].to_numpy(dtype=float),
    )

    family_st0 = _family_by_pb(case, w0, case.rates)
    family_st2b = _family_by_pb(case, w0, rates_st2b)
    for pb_id in case.providers["pb_id"]:
        if pb_id in top_two:
            assert family_st2b[pb_id] == pytest.approx(1.5 * family_st0[pb_id], rel=1e-9, abs=1e-6)
        else:
            assert family_st2b[pb_id] == pytest.approx(family_st0[pb_id], rel=1e-9, abs=1e-6)

    addon_st0 = _addon_by_pb(case, w0, case.rates)
    addon_st2b = _addon_by_pb(case, w0, rates_st2b)
    np.testing.assert_allclose(
        addon_st2b.to_numpy(dtype=float),
        addon_st0.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-6,
    )


def test_s5_st3_leaves_no_position_at_terminated_pb(stress_case):
    case, _, result = stress_case
    summary = result.summary.set_index("scenario")
    terminated = summary.loc["ST3", "terminated_pb"]
    pb_ids = case.providers["pb_id"].tolist()
    weights = result.weights["ST3"]
    assert np.abs(weights[:, pb_ids.index(terminated)]).max() <= 1e-12

    row = summary.loc["ST3"]
    if row["status"] == "infeasible":
        assert float(row["total_slack_usd"]) > 0.0
        assert max(
            float(row["slack_capacity_usd"]),
            float(row["slack_counterparty_usd"]),
            float(row["slack_borrow_usd"]),
        ) > 1e-6
    else:
        assert row["status"] == "optimal"
        assert float(row["total_slack_usd"]) <= 1e-6


def test_s6_additional_funding_requirement_identity(stress_case):
    _, _, result = stress_case
    for row in result.summary.itertuples(index=False):
        assert float(row.additional_funding_requirement_usd) == pytest.approx(
            float(row.delta_margin_usd) + float(row.total_slack_usd), abs=1e-6
        )
        assert float(row.total_slack_usd) == pytest.approx(
            float(row.slack_capacity_usd)
            + float(row.slack_counterparty_usd)
            + float(row.slack_borrow_usd),
            abs=1e-6,
        )
        if row.status == "optimal":
            assert float(row.slack_capacity_usd) == 0.0
            assert float(row.slack_counterparty_usd) == 0.0
            assert float(row.slack_borrow_usd) == 0.0


def test_s7_st3_netting_with_offsets_not_above_without_offsets(stress_case):
    _, _, result = stress_case
    netting = result.st3_netting
    receiving = netting[netting["role"].eq("receiving")]
    assert len(receiving) > 0
    assert (
        receiving["margin_with_offsets_usd"].to_numpy(dtype=float)
        <= receiving["margin_without_offsets_usd"].to_numpy(dtype=float) + 1e-6
    ).all()
    total = netting[netting["role"].eq("total")].iloc[0]
    assert float(total["margin_with_offsets_usd"]) <= float(
        total["margin_without_offsets_usd"]
    ) + 1e-6
    assert (netting["netting_benefit_usd"].to_numpy(dtype=float) >= -1e-6).all()
    assert netting["identity_residual_usd"].abs().max() <= 1e-6


def test_scenario_inputs_materialise_fixed_transforms(stress_case):
    case, prices, result = stress_case
    original_book = case.book.copy(deep=True)
    original_rates = case.rates.copy(deep=True)

    st0 = scenario_inputs(case, "ST0", prices=prices, st0=result)
    assert st0.book.equals(case.book)
    assert st0.rates.equals(case.rates)
    assert st0.providers.equals(case.providers)
    assert st0.borrow.equals(case.borrow)
    assert st0.cost_window_start == AS_OF
    assert st0.terminated_pb is None
    assert st0.top_two is None

    st1a = scenario_inputs(case, "ST1a", prices=prices, st0=result)
    st1b = scenario_inputs(case, "ST1b", prices=prices, st0=result)
    for transformed in (st1a, st1b):
        assert transformed.rates.equals(case.rates)
        assert transformed.providers.equals(case.providers)
        assert transformed.borrow.equals(case.borrow)
        assert transformed.solve_providers.equals(case.providers)
        assert transformed.solve_rates.equals(case.rates)
        assert transformed.solve_borrow.equals(case.borrow)
    assert not st1a.book["vol_bucket"].equals(st1b.book["vol_bucket"])

    st2a = scenario_inputs(case, "ST2a", prices=prices, st0=result)
    np.testing.assert_allclose(
        st2a.rates["base_rate"].to_numpy(dtype=float),
        1.5 * case.rates["base_rate"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_array_equal(
        st2a.rates["financing_spread_bps"].to_numpy(dtype=float),
        case.rates["financing_spread_bps"].to_numpy(dtype=float),
    )

    st2b = scenario_inputs(case, "ST2b", prices=prices, st0=result)
    assert st2b.top_two == ("PB_D", "PB_A")
    shocked = st2b.rates["pb_id"].isin(st2b.top_two)
    np.testing.assert_allclose(
        st2b.rates.loc[shocked, "base_rate"].to_numpy(dtype=float),
        1.5 * case.rates.loc[shocked, "base_rate"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_array_equal(
        st2b.rates.loc[~shocked, "base_rate"].to_numpy(dtype=float),
        case.rates.loc[~shocked, "base_rate"].to_numpy(dtype=float),
    )

    st3 = scenario_inputs(case, "ST3", prices=prices, st0=result)
    assert st3.terminated_pb == "PB_D"
    assert st3.notice_days == 126
    assert st3.nav_trigger_pct == 29.1
    assert st3.cost_window_start == "2027-03-05"
    assert st3.book.equals(case.book)
    assert st3.rates.equals(case.rates)
    assert st3.solve_providers["pb_id"].tolist() == ["PB_A", "PB_B", "PB_C"]
    assert st3.solve_rates["pb_id"].isin(["PB_A", "PB_B", "PB_C"]).all()
    assert not st3.solve_borrow["pb_id"].eq("PB_D").any()
    assert not st3.solve_borrow["borrow_available_usd"].eq(0.0).any()
    assert st3.borrow.equals(case.borrow)
    assert st3.notional_to_move_usd == pytest.approx(2_912_025_250.525632, rel=1e-12)
    assert st3.positions_moved == 106

    st4 = scenario_inputs(case, "ST4", prices=prices, st0=result)
    assert st4.terminated_pb == "PB_D"
    assert st4.cost_window_start == "2027-03-05"
    assert st4.top_two == ("PB_D", "PB_A")
    assert st4.notional_to_move_usd == pytest.approx(st3.notional_to_move_usd)
    assert st4.positions_moved == st3.positions_moved == 106
    pd.testing.assert_series_equal(
        st4.book["vol_bucket"], st1a.book["vol_bucket"], check_names=False
    )
    np.testing.assert_allclose(
        st4.rates["base_rate"].to_numpy(dtype=float),
        st2b.rates["base_rate"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )
    assert st4.solve_providers["pb_id"].tolist() == ["PB_A", "PB_B", "PB_C"]

    # The transform function must not mutate the loaded Phase 1 case.
    assert case.book.equals(original_book)
    assert case.rates.equals(original_rates)
    with pytest.raises(ValueError, match="unknown scenario"):
        scenario_inputs(case, "ST9", prices=prices, st0=result)


def test_prereg_section7_facts(stress_case):
    case, prices, result = stress_case
    st0_margin = (
        result.margin_by_pb[result.margin_by_pb["scenario"].eq("ST0")]
        .set_index("pb_id")["margin_usd"]
    )
    expected_margin = {
        "PB_A": 477_120_106.135151,
        "PB_B": 211_730_389.000000,
        "PB_C": 293_929_811.492475,
        "PB_D": 764_910_552.835689,
    }
    for pb_id, expected in expected_margin.items():
        assert round(float(st0_margin[pb_id]), 2) == round(expected, 2)
    assert round(float(st0_margin.sum()), 2) == round(1_747_690_859.463315, 2)

    st2b = scenario_inputs(case, "ST2b", prices=prices, st0=result)
    st3 = scenario_inputs(case, "ST3", prices=prices, st0=result)
    assert st2b.top_two == ("PB_D", "PB_A")
    assert st3.terminated_pb == "PB_D"
    assert st3.notice_days == 126
    assert st3.nav_trigger_pct == 29.1
    assert st3.cost_window_start == "2027-03-05"
    capacity = case.providers.set_index("pb_id").loc["PB_D", "capacity_usd"]
    assert float(capacity) == 3_948_127_000.0
    assert st3.notional_to_move_usd == pytest.approx(2_912_025_250.525632, rel=1e-12)
    assert st3.positions_moved == 106
    assert len(case.book) == 214

    products = case.book["product_id"].nunique()
    assert products == 73
    base_buckets = case.book.groupby("product_id")["vol_bucket"].first()
    st1a_buckets = scenario_inputs(case, "ST1a", prices=prices, st0=result).book.groupby(
        "product_id"
    )["vol_bucket"].first()
    st1b_buckets = scenario_inputs(case, "ST1b", prices=prices, st0=result).book.groupby(
        "product_id"
    )["vol_bucket"].first()
    moved = base_buckets.ne(st1a_buckets)
    assert int(moved.sum()) == 27
    assert int(((base_buckets == "V1") & (st1a_buckets == "V2")).sum()) == 9
    assert int(((base_buckets == "V2") & (st1a_buckets == "V3")).sum()) == 18
    assert int((base_buckets == "V3").sum()) == 42
    assert int(base_buckets.ne(st1b_buckets).sum()) == 22


def test_s6_written_csvs_identity_and_row_counts(stress_case, tmp_path):
    case, _, result = stress_case
    write_outputs(result, tmp_path)
    summary = pd.read_csv(tmp_path / "stress_summary.csv")
    margin = pd.read_csv(tmp_path / "stress_margin_by_pb.csv")
    moves = pd.read_csv(tmp_path / "stress_moves.csv")
    netting = pd.read_csv(tmp_path / "stress_st3_netting.csv")
    sensitivity = pd.read_csv(tmp_path / "stress_bucket_sensitivity.csv")

    assert list(summary["scenario"]) == list(SCENARIOS)
    assert len(summary) == 7
    assert len(margin) == 28
    assert margin["scenario"].nunique() == 7
    assert margin["pb_id"].nunique() == 4
    assert len(netting) == 5
    assert netting["pb_id"].tolist() == ["PB_A", "PB_B", "PB_C", "PB_D", "TOTAL"]
    assert len(sensitivity) == 1
    assert len(moves) > 0
    assert set(moves["scenario"]).issubset(set(SCENARIOS))
    assert len(moves[moves["scenario"].eq("ST0")]) == 0

    for row in summary.itertuples(index=False):
        assert float(row.additional_funding_requirement_usd) == pytest.approx(
            float(row.delta_margin_usd) + float(row.total_slack_usd), abs=1e-6
        )
        assert float(row.total_slack_usd) == pytest.approx(
            float(row.slack_capacity_usd)
            + float(row.slack_counterparty_usd)
            + float(row.slack_borrow_usd),
            abs=1e-6,
        )
        if row.status == "optimal":
            assert (
                float(row.slack_capacity_usd)
                + float(row.slack_counterparty_usd)
                + float(row.slack_borrow_usd)
            ) <= 1e-6

    st3 = summary.set_index("scenario").loc["ST3"]
    st4 = summary.set_index("scenario").loc["ST4"]
    moved_from_terminated = moves[
        moves["scenario"].eq("ST3")
        & moves["from_pb"].eq(st3["terminated_pb"])
    ]["notional_moved_usd"].sum()
    assert float(moved_from_terminated) == pytest.approx(
        float(st3["notional_to_move_usd"]), rel=0.0, abs=1e-6
    )
    assert float(st4["notional_to_move_usd"]) == pytest.approx(
        float(st3["notional_to_move_usd"]), rel=0.0, abs=1e-6
    )
    assert float(st4["notional_to_move_usd"]) == pytest.approx(
        2_912_025_250.525632, rel=1e-12
    )
    raw_summary = (tmp_path / "stress_summary.csv").read_text(encoding="utf-8")
    assert "29.100000000000001" not in raw_summary
    assert float(st3["nav_trigger_pct"]) == 29.1
    assert float(st4["nav_trigger_pct"]) == 29.1
    st3_pb = margin[
        margin["scenario"].eq("ST3")
        & margin["pb_id"].eq(st3["terminated_pb"])
    ].iloc[0]
    assert float(st3_pb["capacity_usd"]) == 0.0
    assert float(st3_pb["gross_usd"]) == 0.0
    assert float(st3_pb["utilisation_pct"]) == 0.0


def test_73_product_buckets_match_phase1_vol_bucket_rule(stress_case):
    case, prices, result = stress_case
    st1a = scenario_inputs(case, "ST1a", prices=prices, st0=result)
    st1b = scenario_inputs(case, "ST1b", prices=prices, st0=result)
    base_buckets = case.book.groupby("product_id")["vol_bucket"].first()
    st1a_buckets = st1a.book.groupby("product_id")["vol_bucket"].first()
    st1b_buckets = st1b.book.groupby("product_id")["vol_bucket"].first()

    assert len(base_buckets) == 73
    assert set(st1a_buckets.index) == set(base_buckets.index)
    assert set(st1b_buckets.index) == set(base_buckets.index)
    assert case.book.groupby("product_id")["vol_bucket"].nunique().eq(1).all()

    for product_id in base_buckets.index:
        closes = prices.loc[prices["product_id"].eq(product_id)].set_index("date")["close"]
        assert base_buckets[product_id] == vol_bucket(closes, AS_OF, 0.10, 0.20)
        expected_st1a = vol_bucket(closes, AS_OF, 0.10 / 2.0, 0.20 / 2.0)
        expected_st1b = vol_bucket(closes, AS_OF, 0.10 / 1.5, 0.20 / 1.5)
        assert st1a_buckets[product_id] == expected_st1a
        assert st1b_buckets[product_id] == expected_st1b
        assert stressed_vol_bucket(closes, AS_OF, 2.0) == expected_st1a
        assert stressed_vol_bucket(closes, AS_OF, 1.5) == expected_st1b

