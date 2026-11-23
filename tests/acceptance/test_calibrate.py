"""Acceptance tests C1–C5 for the Phase 2b calibration core (spec §2, §7).

These tests are self-contained: they build synthetic and hand-worked samples
and read only the committed Phase 1 inputs, because data/public/raw/ is
git-ignored and absent in CI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mfl.calibrate import (
    apc_target,
    calibrate_rates,
    es_recent,
    es_stress,
    es_two_sided,
    es_var,
    h_day_returns,
    reference_rate,
)
from mfl.margin import margin_by_pb, margin_detail

REPO = Path(__file__).resolve().parents[2]


def _c1_losses_120() -> np.ndarray:
    """120 distinct losses: 10, 7, 5 then 117 irregular values below 1."""
    tail = [0.9 - 0.9 * (i / 116.0) ** 1.5 for i in range(117)]
    return np.array([10.0, 7.0, 5.0, *tail], dtype=float)


def _c1_losses_40() -> np.ndarray:
    """40 distinct losses: 3.25, 2.75 then 38 values from 2.4 down to 0.05."""
    return np.array([3.25, 2.75, *np.linspace(2.4, 0.05, 38)], dtype=float)


# --- C1: ES / VaR tail rule (§2.1) -----------------------------------------


def test_c1_es_975_is_mean_of_three_largest_and_var_99_is_second_largest():
    losses = _c1_losses_120()
    assert len(losses) == 120
    assert len(np.unique(losses)) == 120

    es, var = es_var(losses, 0.975)
    assert es == pytest.approx(22.0 / 3.0, abs=1e-12)
    assert var == pytest.approx(5.0, abs=1e-12)

    es_99, var_99 = es_var(losses, 0.99)
    assert es_99 == pytest.approx(8.5, abs=1e-12)
    assert var_99 == pytest.approx(7.0, abs=1e-12)


def test_c1_n40_k_is_one_so_es_975_is_the_largest_loss():
    losses = _c1_losses_40()
    assert len(losses) == 40

    es, var = es_var(losses, 0.975)
    assert es == pytest.approx(3.25, abs=1e-12)
    assert var == pytest.approx(3.25, abs=1e-12)


def test_c1_result_does_not_depend_on_input_order():
    losses = _c1_losses_120()
    shuffled = losses[np.random.default_rng(42).permutation(len(losses))]
    assert es_var(shuffled, 0.975) == es_var(losses, 0.975)


def test_c1_rejects_empty_sample_and_invalid_alpha():
    with pytest.raises(ValueError, match="at least one"):
        es_var(np.array([]), 0.975)
    for alpha in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="alpha"):
            es_var(np.array([1.0, 2.0]), alpha)
    with pytest.raises(ValueError, match="finite"):
        es_var(np.array([1.0, np.nan]), 0.975)


# --- C2: overlapping h-day returns (§1.3, §2) ------------------------------


def _c2_daily(n: int = 40) -> pd.Series:
    """Daily log returns that are exact multiples of 1/1024, so any window sum is exact."""
    values = np.array([(i * 37 % 41 - 20) / 1024.0 for i in range(n)])
    index = pd.bdate_range("2026-01-05", periods=n)
    return pd.Series(values, index=index, name="return")


def test_c2_length_and_window_end_dates():
    daily = _c2_daily()
    h = 5
    result = h_day_returns(daily, h)
    assert len(result) == len(daily) - h + 1
    pd.testing.assert_index_equal(result.index, daily.index[h - 1:])
    assert result.index[-1] == daily.index[-1]
    assert result.name == daily.name

    full = h_day_returns(daily, len(daily))
    assert len(full) == 1
    assert full.iloc[0] == sum(daily.to_numpy())


def test_c2_first_value_is_the_sum_of_the_first_h_daily_returns():
    daily = _c2_daily()
    h = 5
    result = h_day_returns(daily, h).to_numpy()
    # Every return is a multiple of 1/1024, so the sum is exact in any order.
    assert result[0] == sum(daily.to_numpy()[:h])
    for i in range(len(result)):
        assert result[i] == sum(daily.to_numpy()[i : i + h])


def test_c2_h1_returns_the_daily_series_unchanged():
    daily = _c2_daily()
    pd.testing.assert_series_equal(h_day_returns(daily, 1), daily, check_exact=True)


def test_c2_rejects_bad_h_unsorted_duplicate_and_missing_values():
    daily = _c2_daily(10)
    with pytest.raises(ValueError, match="at least 1"):
        h_day_returns(daily, 0)
    with pytest.raises(ValueError, match="daily returns"):
        h_day_returns(daily, 40)
    with pytest.raises(ValueError, match="sorted"):
        h_day_returns(daily.iloc[::-1], 2)

    repeated = pd.to_datetime(["2026-01-05", "2026-01-05", "2026-01-06"])
    duplicated = pd.Series([0.01, 0.02, 0.03], index=repeated, name="return")
    with pytest.raises(ValueError, match="duplicate"):
        h_day_returns(duplicated, 2)

    broken = daily.copy()
    broken.iloc[3] = np.nan
    with pytest.raises(ValueError, match="finite"):
        h_day_returns(broken, 2)
    with pytest.raises(ValueError, match="whole number"):
        h_day_returns(daily, 2.7)


# --- C3: APC identity with floor (§2.2–§2.4) -------------------------------

# MPOR by product type, as registered in §1.1.
_MPOR_BY_TYPE = {
    "irs_proxy_future": 2,
    "commodity_future": 2,
    "cds_proxy": 5,
    "cash_equity": 10,
    "equity_swap": 10,
    "fx_forward": 10,
    "govt_bond": 10,
}


def test_c3_apc_identity_with_and_without_a_binding_floor():
    # ES_stress above ES_recent: the 75/25 blend sets the target.
    target, binding = apc_target(0.05, 0.09)
    assert target == pytest.approx(0.75 * 0.05 + 0.25 * 0.09, abs=1e-15)
    assert target > 0.05
    assert binding is False

    # ES_stress below ES_recent: the floor sets the target.
    target, binding = apc_target(0.08, 0.02)
    assert target == 0.08
    assert binding is True

    # Equality: the floor does not bind.
    target, binding = apc_target(0.08, 0.08)
    assert target == 0.08
    assert binding is False


def test_c3_es_two_sided_measures_both_tails():
    # n = 5 at 97.5% gives k = 1, so each tail is its single worst loss.
    # Long losses are −R, short losses are +R.
    returns = pd.Series([0.10, -0.05, 0.02, -0.20, 0.01])
    result = es_two_sided(returns, 0.975)
    assert result["long"] == pytest.approx(0.20, abs=1e-15)
    assert result["short"] == pytest.approx(0.10, abs=1e-15)
    assert result["es"] == result["long"]


def test_c3_es_two_sided_sign_flip_swaps_the_tails():
    returns = _c2_daily()
    flipped = es_two_sided(-returns, 0.975)
    direct = es_two_sided(returns, 0.975)
    assert flipped["long"] == pytest.approx(direct["short"], abs=1e-15)
    assert flipped["short"] == pytest.approx(direct["long"], abs=1e-15)
    assert flipped["es"] == pytest.approx(direct["es"], abs=1e-15)


def test_c3_es_recent_window_is_open_left_closed_right():
    d = pd.Timestamp("2026-06-30")
    cutoff = d - pd.DateOffset(years=2)
    index = pd.DatetimeIndex([cutoff, cutoff + pd.Timedelta(days=1), d])
    returns = pd.Series([-0.50, 0.0, 0.0], index=index)

    recent = es_recent(returns, d, years=2)
    assert recent["n"] == 2
    assert recent["long"] == pytest.approx(0.0, abs=1e-15)

    wider = es_recent(returns, d, years=3)
    assert wider["n"] == 3
    assert wider["long"] == pytest.approx(0.50, abs=1e-15)
    assert wider["es"] == pytest.approx(0.50, abs=1e-15)


def test_c3_es_recent_lookback_length_changes_the_measure():
    d = pd.Timestamp("2026-06-30")
    index = pd.bdate_range("2019-01-01", d)
    one_year_ago = d - pd.DateOffset(years=1)
    two_years_ago = d - pd.DateOffset(years=2)
    values = np.where(
        index > one_year_ago, 0.01, np.where(index > two_years_ago, -0.10, 0.001)
    )
    returns = pd.Series(values, index=index)

    one_year = es_recent(returns, d, years=1)
    two_years = es_recent(returns, d, years=2)
    assert one_year["n"] == int(((index > one_year_ago) & (index <= d)).sum())
    assert two_years["n"] == int(((index > two_years_ago) & (index <= d)).sum())
    # The last year holds only positive returns, so its ES is the mild short tail.
    assert one_year["es"] == pytest.approx(0.01, abs=1e-15)
    # The two-year window adds the earlier −10% block, a far larger long loss.
    assert two_years["es"] == pytest.approx(0.10, abs=1e-15)


def test_c3_es_stress_is_the_worst_window_ending_on_or_before_d():
    index = pd.bdate_range("2015-01-01", periods=300)
    values = np.zeros(300)
    values[40] = -1.0
    values[290] = -1.2
    returns = pd.Series(values, index=index)

    # window = 250 gives k = 7; the −1.2 block is the only one containing day 290.
    stress, end = es_stress(returns, index[-1], window=250)
    assert stress == pytest.approx(1.2 / 7.0, abs=1e-15)
    assert end == index[290]

    # Point-in-time: before day 290 the worst block is the −1.0 one, and a tie
    # is broken by the earliest block, whose window ends at day 249.
    earlier, earlier_end = es_stress(returns, index[280], window=250)
    assert earlier == pytest.approx(1.0 / 7.0, abs=1e-15)
    assert earlier_end == index[249]

    with pytest.raises(ValueError, match="at least 250"):
        es_stress(returns.iloc[:100], index[99], window=250)


def test_c3_apc_target_never_falls_below_es_recent_on_every_date():
    dates = pd.bdate_range("2015-01-01", "2026-10-30")
    step = np.arange(len(dates), dtype=float)
    daily = pd.Series(0.0011 * np.sin(step / 13) + 0.0009 * np.cos(step / 41), index=dates)
    grid = pd.date_range("2019-01-31", "2026-09-30", freq="ME")

    by_mpor = {h: h_day_returns(daily, h) for h in sorted(set(_MPOR_BY_TYPE.values()))}
    for product_type, mpor in _MPOR_BY_TYPE.items():
        h_returns = by_mpor[mpor]
        for d in grid:
            recent = es_recent(h_returns, d)
            stress, _ = es_stress(h_returns, d)
            target, binding = apc_target(recent["es"], stress)
            assert target >= recent["es"], f"{product_type} on {d.date()}"
            assert binding == (stress < recent["es"])


def test_c3_es_stress_equals_es_two_sided_on_general_returns():
    # The zero-filled cases above cannot detect a sign or slice error in the
    # single-sort window maths, so compare it with es_var through es_two_sided.
    rng = np.random.default_rng(20261123)

    # Exactly one block, so the rolling maximum is that block's two-sided ES.
    dates = pd.bdate_range("2015-01-01", periods=250)
    returns = pd.Series(rng.normal(0.0, 0.01, 250), index=dates)
    stress, end = es_stress(returns, dates[-1], window=250)
    assert stress == pytest.approx(es_two_sided(returns)["es"], abs=1e-15)
    assert end == dates[-1]

    # Many blocks. The maximum only exercises the tail that dominates, so shock
    # the seeded sample once downwards and once upwards to test both tails.
    longer = pd.bdate_range("2015-01-01", periods=300)
    base = rng.normal(0.0, 0.01, 300)
    for shock in (-0.08, 0.08):
        values = base.copy()
        values[150] = shock
        sample = pd.Series(values, index=longer)
        stress, end = es_stress(sample, longer[-1], window=250)
        windows = (sample.iloc[i : i + 250] for i in range(len(sample) - 250 + 1))
        assert stress == pytest.approx(
            max(es_two_sided(window)["es"] for window in windows), abs=1e-15
        ), f"shock {shock}"
        # The reported end date belongs to a window that attains the maximum.
        assert end in longer[249:]
        assert es_two_sided(sample.loc[:end].iloc[-250:])["es"] == pytest.approx(stress, abs=1e-15)


# --- C4/C5: mapping back to product rows (§2.5–§2.6) -----------------------

# Hand-set calibration inputs: no proxy data is available in CI, so T and the
# volatility bucket are chosen here rather than estimated in §2.2–§2.4.
C4_TARGETS = {
    "cash_equity": 0.075,
    "cds_proxy": 0.055,
    "commodity_future": 0.045,
    "equity_swap": 0.050,
    "fx_forward": 0.020,
    "govt_bond": 0.012,
    "irs_proxy_future": 0.031,
}
C4_BUCKETS = {
    "cash_equity": "V2",
    "cds_proxy": "V3",
    "commodity_future": "V3",
    "equity_swap": "V2",
    "fx_forward": "V1",
    "govt_bond": "V1",
    "irs_proxy_future": "V2",
}
VOL_MULTIPLIERS = {"V1": 1.0, "V2": 1.3, "V3": 1.8}


@pytest.fixture(scope="module")
def calibration_inputs() -> dict:
    """Committed Phase 1 rates and products, calibrated to the hand-set targets."""
    rates = pd.read_csv(REPO / "data/raw/pb_rates.csv")
    products = pd.read_csv(REPO / "data/raw/products.csv")
    calibrated, scalars = calibrate_rates(
        rates, products, C4_TARGETS, C4_BUCKETS, VOL_MULTIPLIERS
    )
    return {"rates": rates, "products": products, "calibrated": calibrated, "scalars": scalars}


def _margin_rates(calibrated: pd.DataFrame) -> pd.DataFrame:
    """Return the calibrated rates under the column name margin_detail reads."""
    rates = calibrated[["pb_id", "product_id", "liquidity_tier", "phi"]].copy()
    rates["base_rate"] = calibrated["base_rate_cal"].to_numpy()
    return rates


def _type_book(products: pd.DataFrame, product_type: str, bucket: str) -> pd.DataFrame:
    """One unit long L1 position per product of the type, at the proxy bucket."""
    product_ids = products.loc[products["product_type"].eq(product_type), "product_id"].to_numpy()
    return pd.DataFrame(
        {
            "product_id": product_ids,
            "liquidity_tier": "L1",
            "vol_bucket": bucket,
            "notional_usd": 1.0,
            "side": 1,
        }
    )


def _margin_params() -> dict:
    """Load the Phase 1 buffer and multipliers in the shape margin_detail expects."""
    params = pd.read_csv(REPO / "data/raw/params.csv").set_index("name")["value"]
    return {
        "vol_multipliers": {bucket: float(params[f"vol_mult_{bucket.lower()}"]) for bucket in VOL_MULTIPLIERS},
        "house_buffer": float(params["house_buffer"]),
    }


def test_c4_family_margin_round_trip_equals_each_type_target(calibration_inputs):
    calibrated = calibration_inputs["calibrated"]
    products = calibration_inputs["products"]
    rates = _margin_rates(calibrated)
    providers = pd.read_csv(REPO / "data/raw/providers.csv")
    params = _margin_params()
    pb_ids = providers["pb_id"].to_list()

    for product_type, target in C4_TARGETS.items():
        book = _type_book(products, product_type, C4_BUCKETS[product_type])
        margins = []
        for column, pb_id in enumerate(pb_ids):
            weights = np.zeros((len(book), len(pb_ids)))
            weights[:, column] = 1.0
            family, _ = margin_detail(book, weights, rates, providers, params)
            at_pb = family.loc[family["pb_id"].eq(pb_id)]
            assert len(at_pb) == len(book)
            margins.extend(at_pb["margin_usd"].to_numpy(dtype=float))
        # gross = net = 1 per position, so phi drops out; the equal-weighted
        # mean over all (PB, product) pairs is the type's pre-buffer target.
        assert float(np.mean(margins)) == pytest.approx(target, abs=1e-9), product_type


def test_c4_house_buffer_sits_on_top_of_the_family_margin(calibration_inputs):
    calibrated = calibration_inputs["calibrated"]
    products = calibration_inputs["products"]
    rates = _margin_rates(calibrated)
    providers = pd.read_csv(REPO / "data/raw/providers.csv")
    params = _margin_params()
    pb_ids = providers["pb_id"].to_list()
    buffer = float(params["house_buffer"])
    assert buffer == pytest.approx(1.15, abs=1e-15)

    book = _type_book(products, "irs_proxy_future", C4_BUCKETS["irs_proxy_future"])
    assert "issuer_id" not in book.columns and "conc_eligible" not in book.columns

    for column, pb_id in enumerate(pb_ids):
        weights = np.zeros((len(book), len(pb_ids)))
        weights[:, column] = 1.0
        family, issuer = margin_detail(book, weights, rates, providers, params)
        assert issuer.empty
        by_pb = margin_by_pb(book, weights, rates, providers, params)
        family_total = float(family.loc[family["pb_id"].eq(pb_id), "margin_usd"].sum())
        assert float(by_pb.loc[by_pb["pb_id"].eq(pb_id), "margin_usd"].iloc[0]) == pytest.approx(
            buffer * family_total, abs=1e-9
        )
        assert float(by_pb.loc[~by_pb["pb_id"].eq(pb_id), "margin_usd"].sum()) == 0.0


def test_c5_every_row_scales_by_its_type_scalar(calibration_inputs):
    rates = calibration_inputs["rates"]
    calibrated = calibration_inputs["calibrated"]
    scalars = calibration_inputs["scalars"]
    keys = ["pb_id", "product_id", "liquidity_tier"]

    assert len(calibrated) == 924
    assert not calibrated.duplicated(keys).any()
    assert set(map(tuple, calibrated[keys].to_numpy())) == set(map(tuple, rates[keys].to_numpy()))
    assert calibrated["product_type"].nunique() == 7

    # The Phase 1 rate is carried through untouched; only the scalar multiplies it.
    rejoined = calibrated.merge(rates, on=keys, validate="one_to_one")
    assert len(rejoined) == len(rates)
    assert (rejoined["base_rate_phase1"] - rejoined["base_rate"]).abs().max() == 0.0

    k_by_type = scalars.set_index("product_type")["k_t"]
    expected = calibrated["product_type"].map(k_by_type).to_numpy(dtype=float)
    ratio = calibrated["base_rate_cal"].to_numpy(dtype=float) / rejoined["base_rate"].to_numpy(dtype=float)
    assert float(np.max(np.abs(ratio - expected))) <= 1e-12


def test_c5_reference_rate_is_the_equal_weighted_l1_mean(calibration_inputs):
    rates = calibration_inputs["rates"]
    products = calibration_inputs["products"]

    for product_type, product_ids in products.groupby("product_type")["product_id"]:
        l1 = rates.loc[
            rates["product_id"].isin(product_ids) & rates["liquidity_tier"].eq("L1"), "base_rate"
        ]
        assert len(l1) == 4 * len(product_ids)
        assert reference_rate(rates, products, product_type) == pytest.approx(
            float(l1.mean()), abs=1e-15
        )

    cash_equity_ids = products.loc[products["product_type"].eq("cash_equity"), "product_id"]
    victim = rates.index[
        rates["product_id"].isin(cash_equity_ids) & rates["liquidity_tier"].eq("L1")
    ][0]
    with pytest.raises(ValueError, match="L1 rate rows"):
        reference_rate(rates.drop(index=victim), products, "cash_equity")
    with pytest.raises(ValueError, match="no products"):
        reference_rate(rates, products, "no_such_type")


def test_c5_calibrate_rates_needs_exactly_one_product_per_rate_row(calibration_inputs):
    rates = calibration_inputs["rates"]
    products = calibration_inputs["products"]

    # A rate row whose product_id is not in products cannot be mapped back to
    # a type, so the join must be refused rather than silently dropped (§1.1).
    unknown = rates.copy()
    unknown.loc[0, "product_id"] = "NO_SUCH_PRODUCT"
    with pytest.raises(ValueError, match="unmatched"):
        calibrate_rates(unknown, products, C4_TARGETS, C4_BUCKETS, VOL_MULTIPLIERS)

    # A product_id appearing twice would map one rate row to two types.
    duplicated = pd.concat([products, products.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="one row per product_id"):
        calibrate_rates(rates, duplicated, C4_TARGETS, C4_BUCKETS, VOL_MULTIPLIERS)
