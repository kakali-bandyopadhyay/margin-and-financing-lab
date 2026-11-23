from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.fetch_calibration_data import DIGEST_COLUMNS, write_digest


def test_digest_writer_deduplicates_symbols_and_sorts(tmp_path):
    proxy_map = pd.DataFrame(
        [
            ("irs_proxy_future", "DGS10", "FRED", "dgs10_price_return", "8.1757"),
            ("commodity_future", "GLD", "Tiingo", "log_adj_close", ""),
            ("cds_proxy", "HYG", "Tiingo", "log_adj_close", ""),
            ("cash_equity", "SPY", "Tiingo", "log_adj_close", ""),
            ("equity_swap", "SPY", "Tiingo", "log_adj_close", ""),
            ("fx_forward", "DEXUSEU", "FRED", "log_rate", ""),
            ("govt_bond", "DGS10", "FRED", "dgs10_price_return", "8.1757"),
        ],
        columns=["product_type", "proxy_symbol", "source", "return_type", "duration"],
    )
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    fetched = {
        "SPY": pd.DataFrame({"date": dates, "value": [100.0, 101.0, 102.0]}),
        "GLD": pd.DataFrame({"date": dates, "value": [50.0, 51.0, 52.0]}),
        "HYG": pd.DataFrame({"date": dates, "value": [80.0, 81.0, 80.5]}),
        "DGS10": pd.DataFrame({"date": dates, "value": [4.0, 4.1, 3.9]}),
        "DEXUSEU": pd.DataFrame({"date": dates, "value": [1.1, 1.2, 1.15]}),
    }

    output = tmp_path / "calibration_inputs_digest.csv"
    written = write_digest(proxy_map, fetched, "2026-11-23", output)
    reread = pd.read_csv(output)
    expected_symbols = ["DEXUSEU", "DGS10", "GLD", "HYG", "SPY"]
    assert list(written.columns) == DIGEST_COLUMNS
    assert written["symbol"].tolist() == expected_symbols
    assert reread["symbol"].tolist() == expected_symbols
    assert len(written) == len(expected_symbols)
    assert len(set(written["symbol"])) == len(expected_symbols)
