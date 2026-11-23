from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from mfl.cli import main
from mfl.calibrate import kupiec, traffic_light


REPO = Path(__file__).resolve().parents[2]


def _fixture_raw(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2015-01-01", "2026-10-30")
    symbols = pd.read_csv(REPO / "data/public/calibration_proxies.csv")["proxy_symbol"].drop_duplicates()
    for symbol in symbols:
        if symbol == "DGS10":
            values = [4.0 + 0.25 * math.sin(i / 21) for i in range(len(dates))]
        else:
            base = 1.1 if symbol == "DEXUSEU" else 100.0
            values = [base * math.exp(0.0001 * i + 0.01 * math.sin(i / 19)) for i in range(len(dates))]
        pd.DataFrame({"date": dates, "value": values}).to_csv(path / f"{symbol}.csv", index=False)
    return path


def test_calibrate_cli_dispatch_writes_targets(tmp_path):
    raw = _fixture_raw(tmp_path / "raw")
    out = tmp_path / "out"
    exit_code = main([
        "calibrate", "--seed", "42", "--data", str(REPO / "data"),
        "--raw", str(raw), "--out", str(out),
    ])
    assert exit_code == 0
    assert (out / "calibration_targets.csv").is_file()


def test_kupiec_and_traffic_light_match_hand_computed_cases():
    # LR = -2[(n-x)ln(1-p)+x ln(p)-(n-x)ln(1-x/n)-x ln(x/n)].
    # For (250,0,.01), LR=5.025167926750726, p=erfc(sqrt(LR/2))=.0249815030534497;
    # P(X<=0)=.99^250=.08105851616218128, so the zone is green.
    lr0, p0 = kupiec(250, 0, 0.01)
    assert lr0 == pytest.approx(5.025167926750726, abs=1e-12)
    assert p0 == pytest.approx(0.0249815030534497, abs=1e-12)
    assert traffic_light(250, 0, 0.01) == "green"

    # For (250,8,.01), p-hat=.032 gives LR=7.7335507244945205 and
    # p=.0054204051941277925; sum[k=0..8] C(250,k).01^k.99^(250-k)
    # =.9989434675026412, so the zone is yellow.
    lr8, p8 = kupiec(250, 8, 0.01)
    assert lr8 == pytest.approx(7.7335507244945205, abs=1e-12)
    assert p8 == pytest.approx(0.0054204051941277925, abs=1e-12)
    assert traffic_light(250, 8, 0.01) == "yellow"
