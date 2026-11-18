"""A7: matched-product sanity vs one published exchange margin (sanity only, not calibration)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from mfl.io import load_case
from mfl.margin import margin_by_pb, vol_bucket


BAND = (0.5, 4.0)  # D-06


def test_a7_irsf10y_vs_cbot_zn(data_raw):
    case = load_case(data_raw)
    ref = pd.read_csv(data_raw.parent / "public" / "exchange_margin.csv")
    assert len(ref) == 1
    ref = ref.iloc[0]
    notional = float(ref["settle_price"]) * float(ref["multiplier"])
    exchange_rate = float(ref["initial_margin_usd"]) / notional

    prices = pd.read_csv(data_raw / "price_history.csv", parse_dates=["date"])
    closes = prices.loc[prices["product_id"].eq("IRSF_10Y")].set_index("date")["close"]
    params = case.params
    bucket = vol_bucket(
        closes,
        params["as_of_date"],
        float(params["vol_cut_low"]),
        float(params["vol_cut_high"]),
    )
    assert bucket == "V1"

    book = case.book.loc[case.book["product_id"].eq("IRSF_10Y")].iloc[[0]].copy().reset_index(drop=True)
    book["pos_id"] = "A7"
    book["pm_id"] = "A7"
    book["issuer_id"] = None
    book["conc_eligible"] = False
    book["needs_locate"] = False
    book["side"] = 1
    book["notional_usd"] = notional
    book["liquidity_tier"] = "L1"
    book["vol_bucket"] = bucket

    pb_ids = case.providers["pb_id"].tolist()
    ratios = {}
    for index, pb_id in enumerate(pb_ids):
        weights = np.zeros((1, len(pb_ids)))
        weights[0, index] = 1.0
        by_pb = margin_by_pb(book, weights, case.rates, case.providers, params)
        proxy_margin = float(by_pb.loc[by_pb["pb_id"].eq(pb_id), "margin_usd"].iloc[0])
        ratios[pb_id] = (proxy_margin / notional) / exchange_rate
    print({pb_id: round(ratio, 3) for pb_id, ratio in ratios.items()})
    assert all(BAND[0] <= ratio <= BAND[1] for ratio in ratios.values()), ratios
