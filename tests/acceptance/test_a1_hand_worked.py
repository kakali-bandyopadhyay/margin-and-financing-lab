"""A1: hand-worked margin cases; charge checks wait for attribution step 4.

Allocation-matrix columns follow providers["pb_id"] row order: X is column 0,
Y is column 1. The M1 contract rejects w unless its shape is
(len(book), len(providers)).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mfl.margin import margin_by_pb, total_margin


PMS = ("A", "B")
PBS = ("X", "Y")


def _market() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    # Joined M1 book rows: positions plus product/issuer attributes.
    book = pd.DataFrame(
        [
            {"pos_id": "P1", "pm_id": "A", "product_id": "EQ1", "asset_class": "equity", "product_type": "cash_equity", "issuer_id": "I1", "conc_eligible": True, "needs_locate": True, "side": 1, "notional_usd": 10_000_000.0, "liquidity_tier": "L1", "vol_bucket": "V3"},
            {"pos_id": "P2", "pm_id": "B", "product_id": "EQ1", "asset_class": "equity", "product_type": "cash_equity", "issuer_id": "I1", "conc_eligible": True, "needs_locate": True, "side": -1, "notional_usd": 6_000_000.0, "liquidity_tier": "L1", "vol_bucket": "V3"},
            {"pos_id": "P3", "pm_id": "A", "product_id": "GOV1", "asset_class": "rates", "product_type": "govt_bond", "issuer_id": "SOV1", "conc_eligible": False, "needs_locate": True, "side": 1, "notional_usd": 20_000_000.0, "liquidity_tier": "L1", "vol_bucket": "V1"},
        ]
    )
    rates = pd.DataFrame(
        [
            {"pb_id": pb, "product_id": product, "liquidity_tier": "L1", "base_rate": rate, "phi": 0.60}
            for pb, product, rate in (
                ("X", "EQ1", 0.15),
                ("Y", "EQ1", 0.18),
                ("X", "GOV1", 0.02),
                ("Y", "GOV1", 0.015),
            )
        ]
    )
    providers = pd.DataFrame(
        [{"pb_id": pb, "conc_threshold": 0.25, "conc_rate": 0.02} for pb in PBS]
    )
    params: dict[str, object] = {
        "house_buffer": 1.15,
        "vol_multipliers": {"V1": 1.0, "V2": 1.3, "V3": 1.8},
    }
    return book, rates, providers, params


def _m_by_pb(book, w, rates, providers, params) -> dict[str, float]:
    # Contract: margin_by_pb returns one row per PB with pb_id and margin_usd.
    detail = margin_by_pb(book, w, rates, providers, params)
    return dict(zip(detail["pb_id"], detail["margin_usd"], strict=True))


def _margin_subset(book, w, selector, rates, providers, params) -> float:
    rows = np.flatnonzero(np.asarray(selector, dtype=bool))
    subset = book.iloc[rows].reset_index(drop=True)
    return total_margin(subset, w[rows, :], rates, providers, params)


@pytest.mark.parametrize(
    ("case", "allocation", "expected_by_pb", "expected_usage", "expected_solo"),
    [
        pytest.param(
            "a",
            np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]),
            {"X": 3_353_400.0, "Y": 0.0},
            {"A": 1_386_900.0, "B": -269_100.0},
            {"A": 3_622_500.0, "B": 1_966_500.0},
            id="all-at-X",
        ),
        pytest.param(
            "b",
            np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]),
            {"X": 3_277_500.0, "Y": 2_580_600.0},
            {"A": 3_519_000.0, "B": 2_235_600.0},
            {"A": 3_622_500.0, "B": 2_339_100.0},
            id="long-at-X-shorts-and-bond-at-Y",
        ),
    ],
)
def test_a1_hand_worked_margin(case, allocation, expected_by_pb, expected_usage, expected_solo):
    book, rates, providers, params = _market()
    full_by_pb = _m_by_pb(book, allocation, rates, providers, params)
    full_margin = total_margin(book, allocation, rates, providers, params)

    assert full_by_pb == pytest.approx(expected_by_pb, abs=0.005)
    assert full_margin == pytest.approx(sum(expected_by_pb.values()), abs=0.005)

    usage = {}
    solo = {}
    for pm in PMS:
        is_pm = book["pm_id"].eq(pm).to_numpy()
        usage[pm] = full_margin - _margin_subset(
            book, allocation, ~is_pm, rates, providers, params
        )
        solo[pm] = _margin_subset(
            book, allocation, is_pm, rates, providers, params
        )

    assert usage == pytest.approx(expected_usage, abs=0.005)
    assert solo == pytest.approx(expected_solo, abs=0.005)
    residual = full_margin - sum(usage.values())
    expected_residual = {
        "a": 2_235_600.0,
        "b": 103_500.0,
    }[case]
    assert residual == pytest.approx(expected_residual, abs=0.005)


@pytest.mark.parametrize(
    ("usage", "solo", "total_margin_usd", "expected_share", "expected_charge"),
    [
        pytest.param(
            {"A": 1_386_900.0, "B": -269_100.0},
            {"A": 3_622_500.0, "B": 1_966_500.0},
            3_353_400.0,
            {"A": 35 / 54, "B": 19 / 54},
            {"A": 7_089.75, "B": 1_293.75},
            id="case-a",
        ),
        pytest.param(
            {"A": 3_519_000.0, "B": 2_235_600.0},
            {"A": 3_622_500.0, "B": 2_339_100.0},
            5_858_100.0,
            {"A": 0.6076388888888888, "B": 0.3923611111111111},
            {"A": 8_954.73, "B": 5_690.52},
            id="case-b",
        ),
    ],
)
def test_a1_attribution_shares_and_charges(
    usage, solo, total_margin_usd, expected_share, expected_charge
):
    # Future step-4 contract: DataFrame columns pm_id, share, charge_usd.
    from mfl.attribution import attribute_pm_usage

    result = attribute_pm_usage(
        usage=usage,
        solo_margin=solo,
        total_margin=total_margin_usd,
        pass_through_bps=100.0,
        horizon_days=90,
    )
    actual = result.set_index("pm_id")
    assert actual["share"].to_dict() == pytest.approx(expected_share, abs=1e-10)
    assert actual["charge_usd"].to_dict() == pytest.approx(expected_charge, abs=0.005)
