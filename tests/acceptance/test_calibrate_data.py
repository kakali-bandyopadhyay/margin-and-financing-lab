from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from mfl.calib_data import (
    compare_to_digest,
    digest_row,
    dgs10_price_returns,
    par_bond_duration,
)


def test_c11_dgs10_hand_worked_transform():
    yields = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
            "value": [4.00, 4.10, 3.90],
        }
    )
    duration = par_bond_duration(0.04)
    assert duration == pytest.approx(8.175716672298563, abs=1e-12)
    returns = dgs10_price_returns(yields, duration)
    np.testing.assert_allclose(
        returns.to_numpy(),
        [-0.00820932112953487, 0.016219188308253658],
        atol=1e-12,
        rtol=0,
    )


def test_c13_input_digest_and_reproduction_status():
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, freq="D"),
            "value": [100.0, 101.0, 99.0, 102.0, 103.0],
        }
    )
    expected = digest_row("TEST", "fixture", "value", raw, "2026-11-23")
    assert expected["sha256_raw"] == "c5bcb9c71a4cd5aa875cbb803ce3347a38a293869524cec0740bbb5d5d77ac09"
    assert len(expected["sha256_raw"]) == 64

    rescaled = raw.copy()
    rescaled["value"] *= 1.01
    result = compare_to_digest(rescaled, expected, tol=1e-10)
    assert result["status"] == "within_tolerance"
    assert result["diffs"] == []

    changed = raw.copy()
    changed.loc[2, "value"] += 2.0
    result = compare_to_digest(changed, expected, tol=1e-10)
    assert result["status"] == "not_reproduced"
    assert result["diffs"]
