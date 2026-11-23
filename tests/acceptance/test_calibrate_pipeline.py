from __future__ import annotations

import math
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mfl.calibrate import (
    _apc_driver_rows,
    _backtest_month,
    calibrate_rates,
    apc_target,
    es_stress,
    es_recent,
    es_var,
    h_day_returns,
    kupiec,
    month_end_dates,
    run_calibrated_case,
    test_windows as make_test_windows,
    traffic_light,
)
from mfl.calib_data import par_bond_duration
from mfl.cli import main
from mfl.io import load_case


REPO = Path(__file__).resolve().parents[2]


def _tree_hashes(path: Path) -> dict[str, str]:
    return {
        str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(path.rglob("*")) if file.is_file()
    }


def test_c6a_phase1_summary_total_reproduces_to_cent():
    summary = pd.read_csv(REPO / "reports/run_42/results/run_summary.csv").iloc[0]
    assert summary["status"] == "optimal"
    assert round(float(summary["total_margin_usd"]), 2) == 1_747_690_859.46


def test_c6b_calibrate_cli_writes_only_registered_outputs(tmp_path, monkeypatch):
    run_before = _tree_hashes(REPO / "reports/run_42")
    stress_before = _tree_hashes(REPO / "reports/stress_42")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    dates = pd.bdate_range("2015-01-01", "2026-10-30")
    step = np.arange(len(dates), dtype=float)
    fixtures = {
        "SPY": 100 * np.exp(0.0001 * step + 0.015 * np.sin(step / 19)),
        "GLD": 100 * np.exp(0.0001 * step + 0.012 * np.sin(step / 23)),
        "HYG": 100 * np.exp(0.0001 * step + 0.010 * np.sin(step / 17)),
        "DEXUSEU": 1.1 * np.exp(0.00001 * step + 0.003 * np.sin(step / 29)),
        "DGS10": 4.0 + 0.25 * np.sin(step / 21),
    }
    for symbol, values in fixtures.items():
        pd.DataFrame({"date": dates, "value": values}).to_csv(raw_dir / f"{symbol}.csv", index=False)

    # The checked-in draft deliberately leaves DGS10's duration TBD. For this
    # synthetic-only fixture, supply D calculated at the fixed test yield 4%.
    proxy_path = REPO / "data/public/calibration_proxies.csv"
    original_read_csv = pd.read_csv

    def read_csv_with_test_duration(path, *args, **kwargs):
        frame = original_read_csv(path, *args, **kwargs)
        if Path(path) == proxy_path:
            frame["duration"] = frame["duration"].astype(object)
            frame.loc[frame["return_type"].eq("dgs10_price_return"), "duration"] = par_bond_duration(0.04)
        return frame

    monkeypatch.setattr(pd, "read_csv", read_csv_with_test_duration)
    out_dir = tmp_path / "calib_42"
    try:
        exit_code = main([
            "calibrate", "--seed", "42", "--data", str(REPO / "data"),
            "--raw", str(raw_dir), "--out", str(out_dir),
        ])
    finally:
        assert _tree_hashes(REPO / "reports/run_42") == run_before
        assert _tree_hashes(REPO / "reports/stress_42") == stress_before
    assert exit_code == 0
    expected = [
        "calibration_targets.csv", "backtest.csv", "drivers_irsf.csv",
        "calib_summary.csv", "calib_pm_charges.csv", "calib_moves.csv",
        "calib_binding.csv", "report.html",
    ]
    assert all((out_dir / name).is_file() for name in expected)


def test_c7_point_in_time_measures_ignore_future_and_stress_is_monotone():
    dates = pd.bdate_range("2015-01-01", periods=700)
    step = np.arange(len(dates), dtype=float)
    daily = pd.Series(0.0015 * np.sin(step / 7) + 0.0007 * np.cos(step / 31), index=dates)
    returns = h_day_returns(daily, 2)
    d = pd.Timestamp(returns.index[450])
    future_changed = returns.copy()
    future_changed.loc[future_changed.index > d] *= 10

    recent = es_recent(returns, d)
    recent_changed = es_recent(future_changed, d)
    stress, _ = es_stress(returns, d)
    stress_changed, _ = es_stress(future_changed, d)
    target, _ = apc_target(float(recent["es"]), float(stress))
    changed_target, _ = apc_target(float(recent_changed["es"]), float(stress_changed))
    assert recent == recent_changed
    assert stress == pytest.approx(stress_changed, abs=1e-15)
    assert target == pytest.approx(changed_target, abs=1e-15)

    month_ends = month_end_dates(returns.index, start="2016-09", end="2017-12")
    stress_path = [es_stress(returns, month_end)[0] for month_end in month_ends]
    assert np.all(np.diff(stress_path) >= -1e-15)


def test_c8_calibrated_pm_attribution_sums_to_calibrated_margin():
    case = load_case(REPO / "data/raw")
    products = case.raw_tables["products"][["product_id", "product_type"]]
    hand_rates = case.rates.merge(products, on="product_id", validate="many_to_one")
    hand_rates["base_rate_cal"] = hand_rates["base_rate"] * np.where(
        hand_rates["product_type"].eq("commodity_future"), 2.0, 1.0
    )

    outputs = run_calibrated_case(case, hand_rates)
    total_margin = float(outputs["calib_summary"].iloc[0]["total_margin_usd"])
    pm = outputs["calib_pm_charges"]
    assert float(pm["attributed_margin_calibrated_usd"].sum()) == pytest.approx(total_margin, abs=1e-6)
    pass_through_scale = float(case.params["pass_through_bps"]) * 1e-4 * float(case.params["horizon_days"]) / 360.0
    assert float(pm["charge_calibrated"].sum()) == pytest.approx(total_margin * pass_through_scale, abs=1e-6)


def test_c9_non_overlapping_windows_anchor_on_estimation_date():
    d_m = pd.Timestamp("2026-01-31")
    days = pd.date_range("2026-02-01", periods=21, freq="D")
    prices = pd.Series(100.0 * np.exp(0.01 * np.arange(1, 22)), index=days)
    prices.loc[d_m] = 100.0
    prices = prices.sort_index()

    ten_day = make_test_windows(prices, d_m, 10)
    two_day = make_test_windows(prices, d_m, 2)
    assert len(ten_day) == 2  # 1 day dropped
    assert len(two_day) == 10  # 1 day dropped
    assert ten_day.iloc[0]["start"] == days[0]
    assert ten_day.iloc[0]["end"] == days[9]
    assert ten_day.iloc[0]["return"] == pytest.approx(math.log(prices.loc[days[9]]) - math.log(prices.loc[d_m]))
    assert (ten_day["start"].dt.month == 2).all() and (ten_day["end"].dt.month == 2).all()
    assert (two_day["start"].dt.month == 2).all() and (two_day["end"].dt.month == 2).all()


def test_c10_binomial_traffic_light_and_kupiec_zero_failures():
    assert [traffic_light(250, x) for x in range(5)] == ["green"] * 5
    assert [traffic_light(250, x) for x in range(5, 10)] == ["yellow"] * 5
    assert traffic_light(250, 10) == "red"
    lr, p_value = kupiec(250, 0, 0.01)
    assert lr == pytest.approx(-2 * 250 * math.log(0.99), abs=1e-12)
    assert p_value == pytest.approx(math.erfc(math.sqrt(lr / 2)), abs=1e-12)


def test_c12_es_apc_and_monthly_exceedance_properties():
    rng = np.random.default_rng(20261123)
    losses = rng.normal(0.0, 1.0, size=5000)
    es_975, _ = es_var(losses, 0.975)
    es_99, _ = es_var(losses, 0.99)
    assert es_99 >= es_975

    dates = pd.bdate_range("2018-01-01", periods=900)
    step = np.arange(len(dates) - 1, dtype=float)
    daily = pd.Series(0.0012 * np.sin(step / 9) + 0.0005 * np.cos(step / 27), index=dates[1:])
    base_h_returns = h_day_returns(daily, 2)
    base_recent = es_recent(base_h_returns, pd.Timestamp(base_h_returns.index[-1]))
    base_stress = es_stress(base_h_returns, pd.Timestamp(base_h_returns.index[-1]))[0]
    apc_rows = pd.DataFrame(_apc_driver_rows(
        base_h_returns, pd.Timestamp(base_h_returns.index[-1]), base_recent, base_stress
    ))
    no_apc = float(apc_rows.loc[apc_rows["setting"].eq("none"), "T"].iloc[0])
    assert (apc_rows["T"] >= no_apc - 1e-15).all()

    type_mpor = [
        ("irs_proxy_future", 2), ("commodity_future", 2), ("cds_proxy", 5),
        ("cash_equity", 10), ("equity_swap", 10), ("fx_forward", 10), ("govt_bond", 10),
    ]
    month_ends = month_end_dates(dates, start="2019-12", end="2020-11")
    for type_index, (_product_type, h) in enumerate(type_mpor):
        shifted_daily = daily + 0.00015 * np.sin(step / (11 + type_index))
        h_returns = h_day_returns(shifted_daily, h)
        prices = pd.Series(100.0 * np.exp(np.r_[0.0, shifted_daily.cumsum().to_numpy()]), index=dates)
        for month_end in month_ends:
            monthly = _backtest_month(h_returns, prices, month_end, h)
            by_side = monthly.pivot(index="side", columns="apc", values="exceedances")
            assert (by_side[True] <= by_side[False]).all()
