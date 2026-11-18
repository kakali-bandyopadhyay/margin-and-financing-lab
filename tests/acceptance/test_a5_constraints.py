"""A5: M2 solver contract and allocation constraint acceptance tests.

Result columns follow ``providers["pb_id"]`` order. Only status ``optimal`` is
accepted; ``optimal_inaccurate`` is a failure. Reported margin must be
recomputed by margin.py from the returned allocation. Infeasible books are
re-solved with slacks and identify the blocking constraint block(s). A
needs-locate position with no available PB raises ValueError before solving.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.margin import margin_by_pb, vol_bucket
from mfl.optimise import optimise


AS_OF = "2026-10-30"
VOL_MULTIPLIERS = {"V1": 1.0, "V2": 1.3, "V3": 1.8}
PARAMS = {
    "as_of_date": AS_OF,
    "horizon_days": 90,
    "liquidity_premium_bps": 100.0,
    "house_buffer": 1.15,
    "vol_multipliers": VOL_MULTIPLIERS,
}


def _real_book(data_raw):
    """Load and join source tables, deriving each product's volatility bucket."""
    positions = pd.read_csv(data_raw / "positions.csv")
    products = pd.read_csv(data_raw / "products.csv")
    issuers = pd.read_csv(data_raw / "issuers.csv")
    prices = pd.read_csv(data_raw / "price_history.csv", parse_dates=["date"])

    product_fields = products[
        ["product_id", "product_type", "issuer_id", "needs_locate"]
    ].copy()
    product_fields["needs_locate"] = (
        product_fields["needs_locate"].astype(str).str.upper().eq("TRUE")
    )
    issuer_fields = issuers[["issuer_id", "conc_eligible"]].copy()
    issuer_fields["conc_eligible"] = (
        issuer_fields["conc_eligible"].astype(str).str.upper().eq("TRUE")
    )
    book = positions.merge(product_fields, on="product_id", how="left", validate="many_to_one")
    book = book.merge(issuer_fields, on="issuer_id", how="left", validate="many_to_one")
    book["conc_eligible"] = book["conc_eligible"].astype("boolean").fillna(False).astype(bool)

    buckets = {}
    for product_id, history in prices.groupby("product_id", sort=False):
        closes = history.set_index("date")["close"]
        buckets[product_id] = vol_bucket(closes, AS_OF)
    book["vol_bucket"] = book["product_id"].map(buckets)
    if book["vol_bucket"].isna().any():
        missing = book.loc[book["vol_bucket"].isna(), "product_id"].unique().tolist()
        raise ValueError(f"price history missing for products: {missing}")
    return book


def _load_real_case(data_raw):
    book = _real_book(data_raw)
    rates = pd.read_csv(data_raw / "pb_rates.csv")
    providers = pd.read_csv(data_raw / "providers.csv")
    borrow = pd.read_csv(data_raw / "pb_borrow.csv")
    return book, rates, providers, borrow, dict(PARAMS)


@pytest.fixture(scope="module")
def real_case(data_raw):
    book, rates, providers, borrow, params = _load_real_case(data_raw)
    result = optimise(book, rates, providers, borrow, params)
    return book, rates, providers, borrow, params, result


def _tiny_case(
    *,
    capacities=(100_000_000.0, 100_000_000.0),
    counterparty_limits=(100_000_000.0, 100_000_000.0),
    positions=None,
    borrow_rows=None,
    product_id="FX1",
    product_type="fx_forward",
    asset_class="fx",
):
    """Small no-issuer fixture for isolated infeasibility-block checks."""
    if positions is None:
        positions = [
            ("P1", 1, 4_000_000.0, False, None),
            ("P2", 1, 3_000_000.0, False, None),
            ("P3", -1, 3_000_000.0, False, None),
        ]
    pb_ids = ("X", "Y")
    book = pd.DataFrame(
        [
            {
                "pos_id": pos_id,
                "pm_id": "PM1",
                "product_id": product_id,
                "asset_class": asset_class,
                "product_type": product_type,
                "issuer_id": issuer_id,
                "conc_eligible": False,
                "needs_locate": needs_locate,
                "side": side,
                "notional_usd": notional,
                "liquidity_tier": "L1",
                "vol_bucket": "V1",
            }
            for pos_id, side, notional, needs_locate, issuer_id in positions
        ]
    )
    rates = pd.DataFrame(
        [
            {
                "pb_id": pb_id,
                "product_id": product_id,
                "liquidity_tier": "L1",
                "base_rate": 0.10,
                "financing_spread_bps": 10.0,
                "phi": 0.60,
            }
            for pb_id in pb_ids
        ]
    )
    providers = pd.DataFrame(
        [
            {
                "pb_id": pb_id,
                "capacity_usd": capacity,
                "counterparty_limit_usd": counterparty_limit,
                "conc_threshold": 0.25,
                "conc_rate": 0.02,
            }
            for pb_id, capacity, counterparty_limit in zip(
                pb_ids, capacities, counterparty_limits, strict=True
            )
        ]
    )
    borrow_columns = ["pb_id", "issuer_id", "borrow_fee_bps", "borrow_available_usd"]
    borrow = pd.DataFrame(borrow_rows or [], columns=borrow_columns)
    params = dict(PARAMS)
    return book, rates, providers, borrow, params


def test_a5a_real_book_returns_optimal_solution(real_case):
    _, _, _, _, _, result = real_case
    assert result.status == "optimal"


def test_a5b_position_allocation_constraints(real_case):
    book, _, providers, _, _, result = real_case
    weights = np.asarray(result.w)
    assert weights.shape == (len(book), len(providers))
    assert np.abs(weights.sum(axis=1) - 1.0).max() <= 1e-6
    assert weights.min() >= -1e-9


def test_a5c_capacity_constraints(real_case):
    book, _, providers, _, _, result = real_case
    gross_by_pb = book["notional_usd"].to_numpy(dtype=float) @ np.asarray(result.w)
    capacity = providers["capacity_usd"].to_numpy(dtype=float)
    assert np.all(gross_by_pb - capacity <= 1e-6)


def test_a5d_counterparty_constraints_use_recomputed_margin(real_case):
    book, rates, providers, _, params, result = real_case
    reported = margin_by_pb(book, result.w, rates, providers, params)
    assert reported["pb_id"].tolist() == providers["pb_id"].tolist()
    limits = providers["counterparty_limit_usd"].to_numpy(dtype=float)
    assert np.all(reported["margin_usd"].to_numpy(dtype=float) - limits <= 1e-6)
    np.testing.assert_allclose(
        result.margin_by_pb["margin_usd"].to_numpy(dtype=float),
        reported["margin_usd"].to_numpy(dtype=float),
        atol=1e-6,
        rtol=0.0,
    )


def test_a5e_borrow_limits_and_no_locate_cells(real_case):
    book, _, providers, borrow, _, result = real_case
    weights = np.asarray(result.w)
    pb_ids = providers["pb_id"].tolist()
    available = borrow.set_index(["pb_id", "issuer_id"])["borrow_available_usd"].to_dict()
    short_located = book["side"].eq(-1) & book["needs_locate"].astype(bool)
    no_locate_cells = 0

    for col, pb_id in enumerate(pb_ids):
        for issuer_id, group in book.loc[short_located].groupby("issuer_id", sort=False):
            rows = group.index.to_numpy(dtype=int)
            amount = available.get((pb_id, issuer_id), 0.0)
            if amount <= 0.0:
                no_locate_cells += len(rows)
                assert np.all(np.abs(weights[rows, col]) <= 1e-9)
            else:
                used = float(np.dot(book.loc[rows, "notional_usd"].to_numpy(dtype=float), weights[rows, col]))
                assert used - float(amount) <= 1e-6

    assert no_locate_cells == 34


def test_a5f_solver_margin_epigraph_is_tight(real_case):
    _, _, _, _, _, result = real_case
    recomputed = result.margin_by_pb["margin_usd"].to_numpy(dtype=float)
    solver_values = np.asarray(result.solver_margin_by_pb, dtype=float)
    assert np.max(np.abs(recomputed - solver_values), initial=0.0) <= 1e-6


def test_a5g_capacity_infeasibility_names_capacity_block():
    book, rates, providers, borrow, params = _tiny_case(
        capacities=(4_000_000.0, 4_000_000.0)
    )
    result = optimise(book, rates, providers, borrow, params)
    assert result.status == "infeasible"
    assert result.slack_blocks == {"capacity"}


def test_a5h_counterparty_infeasibility_names_counterparty_block():
    book, rates, providers, borrow, params = _tiny_case(
        counterparty_limits=(1.0, 1.0)
    )
    result = optimise(book, rates, providers, borrow, params)
    assert result.status == "infeasible"
    assert result.slack_blocks == {"counterparty"}


def test_a5i_borrow_infeasibility_names_borrow_block():
    book, rates, providers, borrow, params = _tiny_case(
        positions=[("SHORT", -1, 5_000_000.0, True, "ISS1")],
        borrow_rows=[
            ("X", "ISS1", 30.0, 2_000_000.0),
            ("Y", "ISS1", 30.0, 1_000_000.0),
        ],
        product_id="EQ1",
        product_type="cash_equity",
        asset_class="equity",
    )
    result = optimise(book, rates, providers, borrow, params)
    assert result.status == "infeasible"
    assert result.slack_blocks == {"borrow"}


def test_a5j_needs_locate_with_no_available_pb_fails_before_solving():
    book, rates, providers, borrow, params = _tiny_case(
        positions=[("SHORT_NO_LOCATE", -1, 5_000_000.0, True, "ISS1")],
        product_id="EQ1",
        product_type="cash_equity",
        asset_class="equity",
    )
    with pytest.raises(ValueError, match="SHORT_NO_LOCATE"):
        optimise(book, rates, providers, borrow, params)


def test_a5k_real_book_solution_is_deterministic(real_case):
    book, rates, providers, borrow, params, first = real_case
    second = optimise(book, rates, providers, borrow, params)
    assert first.objective_usd == second.objective_usd
    np.testing.assert_array_equal(first.w, second.w)


def test_a5l_objective_decomposes_and_duals_reported(real_case):
    _, _, _, _, params, result = real_case
    scale = (
        params["liquidity_premium_bps"]
        * 1e-4
        * params["horizon_days"]
        / 360.0
    )
    margin_total = float(result.margin_by_pb["margin_usd"].sum())
    assert abs(result.margin_funding_usd - scale * margin_total) <= 1e-6
    assert abs(result.objective_usd - (result.financing_usd + result.margin_funding_usd)) <= 1e-6
    assert set(result.duals) == {"capacity", "counterparty", "borrow"}
