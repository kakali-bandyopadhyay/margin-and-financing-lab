"""A4: equal-and-opposite FX positions cost more when split across PBs."""

import numpy as np
import pandas as pd
import pytest

from mfl.margin import total_margin


def test_a4_split_hedge_costs_more_without_cross_pb_netting():
    notional = 10_000_000.0
    rate = 0.10
    phi = 0.60
    book = pd.DataFrame(
        [
            {"pos_id": "LONG", "pm_id": "PM_A", "product_id": "FX1", "asset_class": "fx", "product_type": "fx_forward", "issuer_id": None, "conc_eligible": False, "needs_locate": False, "side": 1, "notional_usd": notional, "liquidity_tier": "L1", "vol_bucket": "V1"},
            {"pos_id": "SHORT", "pm_id": "PM_B", "product_id": "FX1", "asset_class": "fx", "product_type": "fx_forward", "issuer_id": None, "conc_eligible": False, "needs_locate": False, "side": -1, "notional_usd": notional, "liquidity_tier": "L1", "vol_bucket": "V1"},
        ]
    )
    rates = pd.DataFrame(
        [
            {"pb_id": pb, "product_id": "FX1", "liquidity_tier": "L1", "base_rate": rate, "phi": phi}
            for pb in ("X", "Y")
        ]
    )
    providers = pd.DataFrame(
        [{"pb_id": pb, "conc_threshold": 0.25, "conc_rate": 0.02} for pb in ("X", "Y")]
    )
    params = {"house_buffer": 1.15, "vol_multipliers": {"V1": 1.0, "V2": 1.3, "V3": 1.8}}

    together = total_margin(
        book,
        np.array([[1.0, 0.0], [1.0, 0.0]]),
        rates,
        providers,
        params,
    )
    split = total_margin(
        book,
        np.array([[1.0, 0.0], [0.0, 1.0]]),
        rates,
        providers,
        params,
    )

    expected_together = 1.15 * rate * (1.0 - phi) * 2.0 * notional
    expected_split = 1.15 * 2.0 * rate * notional
    assert together == pytest.approx(expected_together, abs=1e-6)
    assert split == pytest.approx(expected_split, abs=1e-6)
    assert split > together
