"""A2a–A2g: margin invariants on a small synthetic book."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.margin import total_margin


PBS = ("PB_A", "PB_B", "PB_C")


def _fixture():
    # Seven positions: one conc-eligible corporate issuer, a long/short family,
    # a sovereign, and products without issuers.
    book = pd.DataFrame(
        [
            {"pos_id": "H_LONG", "pm_id": "PM_A", "product_id": "EQ_HEDGE", "asset_class": "equity", "product_type": "cash_equity", "issuer_id": "CORP1", "conc_eligible": True, "needs_locate": True, "side": 1, "notional_usd": 1_000_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "H_SHORT", "pm_id": "PM_B", "product_id": "EQ_HEDGE", "asset_class": "equity", "product_type": "cash_equity", "issuer_id": "CORP1", "conc_eligible": True, "needs_locate": True, "side": -1, "notional_usd": 400_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "EQ_ONLY", "pm_id": "PM_C", "product_id": "EQ_ONLY", "asset_class": "equity", "product_type": "cash_equity", "issuer_id": "CORP1", "conc_eligible": True, "needs_locate": True, "side": 1, "notional_usd": 600_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "SOV", "pm_id": "PM_D", "product_id": "GOV1", "asset_class": "rates", "product_type": "govt_bond", "issuer_id": "SOV1", "conc_eligible": False, "needs_locate": True, "side": 1, "notional_usd": 800_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "FX_LONG", "pm_id": "PM_E", "product_id": "FX1", "asset_class": "fx", "product_type": "fx_forward", "issuer_id": None, "conc_eligible": False, "needs_locate": False, "side": 1, "notional_usd": 500_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "FX_SHORT", "pm_id": "PM_F", "product_id": "FX1", "asset_class": "fx", "product_type": "fx_forward", "issuer_id": None, "conc_eligible": False, "needs_locate": False, "side": -1, "notional_usd": 200_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "COM", "pm_id": "PM_G", "product_id": "COM1", "asset_class": "commodity", "product_type": "commodity_future", "issuer_id": None, "conc_eligible": False, "needs_locate": False, "side": 1, "notional_usd": 300_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
        ]
    )
    products = book["product_id"].drop_duplicates().tolist()
    rates = pd.DataFrame(
        [
            {"pb_id": pb, "product_id": product, "liquidity_tier": "L1", "base_rate": rate, "phi": 0.60}
            for pb, rate in zip(PBS, (0.10, 0.12, 0.11), strict=True)
            for product in products
        ]
    )
    providers = pd.DataFrame(
        [{"pb_id": pb, "conc_threshold": 0.25, "conc_rate": 0.02} for pb in PBS]
    )
    params = {"house_buffer": 1.15, "vol_multipliers": {"V1": 1.0, "V2": 1.3, "V3": 1.8}}
    return book, rates, providers, params


def _draw_weights(seed: int, n_pos: int, n_pb: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.dirichlet(np.ones(n_pb), size=n_pos)


def _margin(book, w, rates, providers, params):
    return total_margin(book, w, rates, providers, params)


def test_a2a_zero_at_zero_and_empty_book():
    book, rates, providers, params = _fixture()
    n_pos, n_pb = len(book), len(PBS)
    assert _margin(book, np.zeros((n_pos, n_pb)), rates, providers, params) == pytest.approx(0.0)
    assert _margin(book.iloc[:0].copy(), np.zeros((0, n_pb)), rates, providers, params) == pytest.approx(0.0)


def test_a2b_non_negative_on_1000_random_feasible_allocations():
    book, rates, providers, params = _fixture()
    weights = _draw_weights(42, len(book), len(PBS))
    assert np.allclose(weights.sum(axis=1), 1.0)
    margins = [_margin(book, w, rates, providers, params) for w in weights]
    assert np.all(np.asarray(margins) >= 0.0)


def test_a2c_monotone_in_position_size_without_opposite_side_in_family():
    book, rates, providers, params = _fixture()
    w = _draw_weights(42, len(book), len(PBS))
    # EQ_ONLY is the only position in its product/tier/bucket family and is
    # conc-eligible under the sole corporate issuer, so scaling it cannot reduce M.
    target = book.index[book["pos_id"].eq("EQ_ONLY")][0]
    baseline = _margin(book, w, rates, providers, params)
    for scale in (1.1, 2.0, 5.0):
        scaled = book.copy()
        scaled.loc[target, "notional_usd"] *= scale
        assert _margin(scaled, w, rates, providers, params) >= baseline - 1e-8


def test_a2d_monotone_in_volatility_bucket():
    book, rates, providers, params = _fixture()
    w = _draw_weights(42, len(book), len(PBS))
    family_rows = book["product_id"].eq("EQ_HEDGE")
    margins = []
    for bucket in ("V1", "V2", "V3"):
        variant = book.copy()
        variant.loc[family_rows, "vol_bucket"] = bucket
        margins.append(_margin(variant, w, rates, providers, params))
    assert margins[0] <= margins[1] <= margins[2]


def test_a2e_convexity_on_1000_random_feasible_pairs():
    book, rates, providers, params = _fixture()
    rng = np.random.default_rng(42)
    n_pos, n_pb = len(book), len(PBS)
    for _ in range(1_000):
        w_a = rng.dirichlet(np.ones(n_pb), size=n_pos)
        w_b = rng.dirichlet(np.ones(n_pb), size=n_pos)
        midpoint = (w_a + w_b) / 2.0
        lhs = _margin(book, midpoint, rates, providers, params)
        rhs = (_margin(book, w_a, rates, providers, params) + _margin(book, w_b, rates, providers, params)) / 2.0
        assert lhs <= rhs + 1e-6


def test_a2f_positive_homogeneity_in_notional():
    book, rates, providers, params = _fixture()
    w = _draw_weights(42, len(book), len(PBS))
    base = _margin(book, w, rates, providers, params)
    assert base > 0.0
    for scale in (0.5, 2.0, 10.0):
        scaled = book.copy()
        scaled["notional_usd"] *= scale
        assert _margin(scaled, w, rates, providers, params) == pytest.approx(
            scale * base, abs=1e-9 * base
        )


def test_a2g_seed_42_draw_and_outputs_are_deterministic():
    book, rates, providers, params = _fixture()
    weights_first = _draw_weights(42, len(book), len(PBS))
    weights_second = _draw_weights(42, len(book), len(PBS))
    np.testing.assert_array_equal(weights_first, weights_second)
    margins_first = np.array([_margin(book, w, rates, providers, params) for w in weights_first])
    margins_second = np.array([_margin(book, w, rates, providers, params) for w in weights_second])
    np.testing.assert_array_equal(margins_first, margins_second)
