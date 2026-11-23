"""Data transforms and stable input-digest helpers for Phase 2b."""

from __future__ import annotations

from hashlib import sha256
import math
from typing import Any

import numpy as np
import pandas as pd


def _series(df: pd.DataFrame) -> pd.Series:
    if "value" not in df.columns:
        raise ValueError("input data must contain a 'value' column")
    values = pd.to_numeric(df["value"], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("input values must be finite numeric observations")
    if "date" in df.columns:
        dates = pd.DatetimeIndex(pd.to_datetime(df["date"], errors="raise")).normalize()
    else:
        dates = pd.DatetimeIndex(pd.to_datetime(df.index, errors="raise")).normalize()
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("input dates must be unique and non-missing")
    order = np.argsort(dates.to_numpy(), kind="stable")
    return pd.Series(
        values.to_numpy(dtype=float)[order],
        index=dates[order],
        name="value",
        dtype=float,
    )


def log_returns(df: pd.DataFrame) -> pd.Series:
    """Return consecutive daily log changes for positive price/rate values."""
    values = _series(df)
    if (values <= 0).any():
        raise ValueError("log-return input values must be positive")
    result = np.log(values).diff().dropna()
    result.name = "return"
    return result


def par_bond_duration(y_star: float) -> float:
    """Modified duration of a 10-year semi-annual par bond at decimal yield."""
    y = float(y_star)
    if not math.isfinite(y) or y <= 0:
        raise ValueError("y_star must be finite and positive")
    return (1.0 / y) * (1.0 - (1.0 + y / 2.0) ** -20)


def dgs10_price_returns(df: pd.DataFrame, D: float) -> pd.Series:
    """Convert DGS10 percentage yields to duration-based daily log returns."""
    duration = float(D)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("D must be finite and positive")
    yields = _series(df) / 100.0
    changes = yields.diff().dropna()
    price_factors = 1.0 - duration * changes
    if (price_factors <= 0).any() or not np.isfinite(price_factors.to_numpy()).all():
        raise ValueError("DGS10 duration approximation produced a non-positive price factor")
    result = np.log(price_factors)
    result.name = "return"
    return result


def price_index_from_returns(r: pd.Series, start: float = 100.0) -> pd.Series:
    """Build a cumulative price index from a dated series of log returns."""
    base = float(start)
    if not math.isfinite(base) or base <= 0:
        raise ValueError("start must be finite and positive")
    values = pd.to_numeric(r, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("returns must be finite numeric values")
    result = base * np.exp(values.astype(float).cumsum())
    result.name = "close"
    return result


def _canonical_raw_frame(df: pd.DataFrame) -> pd.DataFrame:
    values = _series(df)
    return pd.DataFrame(
        {
            "date": values.index.strftime("%Y-%m-%d"),
            "value": [f"{value:.10f}" for value in values.to_numpy(dtype=float)],
        }
    )


def canonical_raw_bytes(df: pd.DataFrame) -> bytes:
    """Serialize date/value observations with fixed decimal precision and LF."""
    return _canonical_raw_frame(df).to_csv(index=False, lineterminator="\n").encode("utf-8")


def _digest_returns(df: pd.DataFrame) -> pd.Series:
    if "return" in df.columns:
        values = pd.to_numeric(df["return"], errors="coerce")
        if "date" in df.columns:
            dates = pd.DatetimeIndex(pd.to_datetime(df["date"], errors="raise")).normalize()
        else:
            dates = pd.DatetimeIndex(pd.to_datetime(df.index, errors="raise")).normalize()
        result = pd.Series(values.to_numpy(dtype=float), index=dates, name="return")
        if result.isna().any() or not np.isfinite(result.to_numpy()).all():
            raise ValueError("return values must be finite numeric observations")
        return result.sort_index(kind="stable")

    return_type = df.attrs.get("return_type", "log_change")
    if return_type == "dgs10_price_return":
        duration = df.attrs.get("duration")
        if duration is None:
            raise ValueError("DGS10 digest requires df.attrs['duration']")
        return dgs10_price_returns(df, float(duration))
    return log_returns(df)


def canonical_return_bytes(df: pd.DataFrame) -> bytes:
    """Serialize the dated daily log-return series to 12 decimal places."""
    returns = _digest_returns(df)
    frame = pd.DataFrame(
        {
            "date": pd.DatetimeIndex(returns.index).strftime("%Y-%m-%d"),
            "return": [f"{value:.12f}" for value in returns.to_numpy(dtype=float)],
        }
    )
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def digest_row(
    symbol: str,
    source: str,
    field: str,
    df: pd.DataFrame,
    fetch_date: str,
) -> dict[str, Any]:
    """Create one digest record for a canonical date/value input series."""
    raw = _canonical_raw_frame(df)
    return {
        "symbol": str(symbol),
        "source": str(source),
        "field": str(field),
        "first_date": str(raw.iloc[0]["date"]) if len(raw) else "",
        "last_date": str(raw.iloc[-1]["date"]) if len(raw) else "",
        "rows": int(len(raw)),
        "sha256_raw": sha256(canonical_raw_bytes(df)).hexdigest(),
        "sha256_returns": sha256(canonical_return_bytes(df)).hexdigest(),
        "fetch_date": pd.Timestamp(fetch_date).date().isoformat(),
    }


def compare_to_digest(
    df: pd.DataFrame,
    digest_row: dict[str, Any] | pd.Series,
    tol: float = 1e-10,
) -> dict[str, Any]:
    """Compare a fetched series with its digest, returning status and differences.

    The committed return digest is over returns rounded to 12 decimal places;
    a matching return digest is therefore within the default 1e-10 tolerance.
    """
    expected = dict(digest_row)
    actual = {
        "sha256_raw": sha256(canonical_raw_bytes(df)).hexdigest(),
        "sha256_returns": sha256(canonical_return_bytes(df)).hexdigest(),
    }
    if actual["sha256_raw"] == expected.get("sha256_raw"):
        return {"status": "identical", "diffs": []}
    if actual["sha256_returns"] == expected.get("sha256_returns"):
        return {"status": "within_tolerance", "diffs": []}
    return {
        "status": "not_reproduced",
        "diffs": [
            {
                "symbol": expected.get("symbol", ""),
                "first_date": expected.get("first_date", ""),
                "last_date": expected.get("last_date", ""),
                "field": "sha256_returns",
                "expected": expected.get("sha256_returns", ""),
                "actual": actual["sha256_returns"],
                "tolerance": float(tol),
            }
        ],
    }
