from __future__ import annotations

import pandas as pd

from mfl.calibrate import BACKTEST_COLUMNS, _aggregate_backtest_months


def test_backtest_aggregates_all_93_months_to_28_sorted_rows():
    product_types = [
        "irs_proxy_future", "commodity_future", "cds_proxy", "cash_equity",
        "equity_swap", "fx_forward", "govt_bond",
    ]
    monthly_rows = []
    for product_type in product_types:
        for side in ("long", "short"):
            for apc in (True, False):
                for month in range(93):
                    monthly_rows.append({
                        "product_type": product_type,
                        "side": side,
                        "apc": apc,
                        "n": 10,
                        "exceedances": int(not apc) + int(side == "short"),
                    })

    result = _aggregate_backtest_months(pd.DataFrame(monthly_rows))

    assert list(result.columns) == BACKTEST_COLUMNS == [
        "product_type", "side", "apc", "n", "exceedances", "rate",
        "kupiec_lr", "kupiec_p", "zone",
    ]
    assert len(result) == 28
    assert result["n"].eq(930).all()
    assert result.groupby(["product_type", "side", "apc"], sort=False).size().eq(1).all()
    assert result.sort_values(
        ["product_type", "side", "apc"], kind="mergesort"
    ).reset_index(drop=True).equals(result)
    for row in result.itertuples(index=False):
        expected = (int(not row.apc) + int(row.side == "short")) * 93
        assert row.exceedances == expected
        assert row.rate == expected / 930
