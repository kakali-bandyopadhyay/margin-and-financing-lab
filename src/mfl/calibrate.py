"""Phase 2b calibration pipeline around author-owned risk measure stubs."""

from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pandas as pd

from .attribution import attribute
from .io import Case, write_csv
from .margin import margin_detail, margin_by_pb, vol_bucket
from .optimise import optimise


# === Core (author: Kakali) ===

def h_day_returns(daily: pd.Series, h: int) -> pd.Series:
    """Overlapping h-day sums of daily log returns, indexed by the window end.

    The result has length n − h + 1: position i holds the sum of daily
    returns i … i+h−1 and is dated by the last day of that window. With h = 1
    the daily series is returned unchanged (the MPOR 1 driver rows).

    The window sum is ``sliding_window_view(...).sum(axis=1)`` rather than a
    pandas rolling sum: rolling can drift by ~1e-17 from the direct sum of the
    same returns, which would break C2's exact first-value assertion.

    The index must be a sorted, duplicate-free date index and the returns must
    be finite, so that each window is a run of consecutive trading days and
    the end date genuinely identifies the window.
    """
    if not isinstance(daily, pd.Series):
        raise TypeError("daily must be a pandas Series")
    try:
        whole_days = float(h)
    except (TypeError, ValueError) as exc:
        raise ValueError("h must be a whole number of trading days") from exc
    if not whole_days.is_integer():
        raise ValueError("h must be a whole number of trading days")
    h = int(whole_days)
    if h < 1:
        raise ValueError("h must be at least 1 trading day")

    if isinstance(daily.index, pd.DatetimeIndex):
        index = daily.index
    else:
        try:
            index = pd.DatetimeIndex(pd.to_datetime(daily.index, errors="raise"))
        except (TypeError, ValueError) as exc:
            raise ValueError("daily must have a date-like index") from exc
    if index.isna().any():
        raise ValueError("daily index must not contain missing dates")
    if not index.is_monotonic_increasing:
        raise ValueError("daily index must be sorted in ascending date order")
    if index.has_duplicates:
        raise ValueError("daily index must not contain duplicate dates")

    values = pd.to_numeric(daily, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("daily returns must be finite numeric values")
    n = len(values)
    if h > n:
        raise ValueError(f"need at least {h} daily returns for h={h}; got {n}")

    array = values.to_numpy(dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(array, h).sum(axis=1)
    return pd.Series(windows, index=index[h - 1:], name=daily.name, dtype=float)


def _tail_count(n: int, alpha: float) -> int:
    """Spec §2.1 tail count k = ceil((1 − α)·n), rounded to 9 decimals first.

    ``es_var`` explains why the rounding is required; every ES in this module
    goes through this one function so the rule cannot drift between them.
    """
    if n < 1:
        raise ValueError("sample size must be at least 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly between 0 and 1")
    return math.ceil(round((1.0 - alpha) * n, 9))


def es_var(losses: np.ndarray, alpha: float) -> tuple[float, float]:
    """Return (ES_α, VaR_α), using k = ceil((1 − α)n) largest losses.

    The product (1 − α)·n is rounded to 9 decimals before the ceiling: in
    binary floating point (1 − 0.975) × 120 is 3.0000000000000027 and
    (1 − 0.975) × 40 is 1.0000000000000009, so a bare ceil would return one
    too many and break the spec's k = 3 / k = 1 cases. ES and VaR use the
    same k: ES is the mean of the k largest losses and VaR is L_(k), the
    k-th largest.
    """
    values = np.asarray(losses, dtype=float).ravel()
    if values.size == 0:
        raise ValueError("losses must contain at least one observation")
    if not np.isfinite(values).all():
        raise ValueError("losses must be finite numeric values")

    n = values.size
    k = _tail_count(n, alpha)
    if k < 1 or k > n:
        raise ValueError(f"tail count k={k} outside 1..{n} for alpha={alpha}")
    ordered = np.sort(values)[::-1]
    return float(ordered[:k].mean()), float(ordered[k - 1])


def _return_values(h_returns: pd.Series | np.ndarray) -> np.ndarray:
    """Return a finite 1-D float array from an h-day return sample."""
    values = np.asarray(h_returns, dtype=float).ravel()
    if values.size == 0:
        raise ValueError("h-day returns must contain at least one observation")
    if not np.isfinite(values).all():
        raise ValueError("h-day returns must be finite numeric values")
    return values


def es_two_sided(h_returns: pd.Series, alpha: float = 0.975) -> dict:
    """Return long, short and worst-side ES; long loss is −R and short loss is +R.

    Both tails are measured on the same sample and the type's measure is the
    larger of the two (§2.1), so a rise in either tail raises ``es``.
    """
    values = _return_values(h_returns)
    long_es, _ = es_var(-values, alpha)
    short_es, _ = es_var(values, alpha)
    return {"long": long_es, "short": short_es, "es": max(long_es, short_es)}


def _whole_years(years: float) -> int:
    """Return ``years`` as an int, refusing fractions that DateOffset cannot express."""
    try:
        whole = int(years)
    except (TypeError, ValueError) as exc:
        raise ValueError("years must be a whole number of years") from exc
    if float(years) != whole:
        raise ValueError("years must be a whole number of years")
    return whole


def es_recent(
    h_returns: pd.Series,
    d: pd.Timestamp,
    years: float = 2.0,
    alpha: float = 0.975,
) -> dict:
    """Apply es_two_sided to returns ending in (d − years, d], and add n.

    The window is open on the left and closed on the right, so a return dated
    exactly d − years is excluded and one dated d is included. ``years`` must
    be whole, because pd.DateOffset treats fractional years as ambiguous.
    """
    if not isinstance(h_returns, pd.Series):
        raise TypeError("h_returns must be a pandas Series")
    if not isinstance(h_returns.index, pd.DatetimeIndex):
        raise ValueError("h_returns must have a DatetimeIndex")
    end = pd.Timestamp(d)
    cutoff = end - pd.DateOffset(years=_whole_years(years))
    sample = h_returns.loc[(h_returns.index > cutoff) & (h_returns.index <= end)]
    if sample.empty:
        raise ValueError(f"no h-day returns ending in ({cutoff:%Y-%m-%d}, {end:%Y-%m-%d}]")
    return {"n": int(len(sample)), **es_two_sided(sample, alpha)}


def es_stress(
    h_returns: pd.Series,
    d: pd.Timestamp,
    window: int = 250,
    alpha: float = 0.975,
) -> tuple[float, pd.Timestamp]:
    """Max two-sided ES over rolling ``window`` blocks ending on or before d.

    Only h-day returns with an end date ≤ d enter, so the measure is
    point-in-time and non-decreasing in d (§2.3). Every block of ``window``
    consecutive returns is scored with the same §2.1 rule, and the earliest
    block breaks a tie. Raises ValueError when fewer than ``window`` returns
    are available: the spec does not define that case and the real run never
    reaches it.
    """
    if not isinstance(h_returns, pd.Series):
        raise TypeError("h_returns must be a pandas Series")
    if not isinstance(h_returns.index, pd.DatetimeIndex):
        raise ValueError("h_returns must have a DatetimeIndex")
    window = int(window)
    if window < 1:
        raise ValueError("window must be at least 1")
    end = pd.Timestamp(d)
    available = h_returns.loc[h_returns.index <= end]
    values = _return_values(available)
    if values.size < window:
        raise ValueError(
            f"need at least {window} h-day returns ending on or before "
            f"{end:%Y-%m-%d}; got {values.size}"
        )
    k = _tail_count(window, alpha)
    if not 1 <= k <= window:
        raise ValueError(f"tail count k={k} outside 1..{window} for alpha={alpha}")
    blocks = np.lib.stride_tricks.sliding_window_view(values, window)
    ordered = np.sort(blocks, axis=1)
    # A long loss is −R, so its k largest values are the k smallest returns;
    # sorting once serves both tails (twice the throughput of sorting each).
    long_es = -ordered[:, :k].mean(axis=1)
    short_es = ordered[:, -k:].mean(axis=1)
    per_block = np.maximum(long_es, short_es)
    best = int(np.argmax(per_block))
    return float(per_block[best]), available.index[best + window - 1]


def apc_target(es_recent_value: float, es_stress_value: float) -> tuple[float, bool]:
    """Floored APC target max(ES_recent, 0.75·ES_recent + 0.25·ES_stress).

    The floor keeps the anti-procyclicality add-on non-negative when the
    stressed window is milder than the recent sample (§2.4). ``floor_binding``
    is True only when ES_stress is strictly below ES_recent; at equality the
    floor does not bind.
    """
    recent = float(es_recent_value)
    stress = float(es_stress_value)
    if not np.isfinite(recent) or not np.isfinite(stress):
        raise ValueError("ES inputs must be finite")
    blend = 0.75 * recent + 0.25 * stress
    return float(max(recent, blend)), bool(stress < recent)


def reference_rate(rates: pd.DataFrame, products: pd.DataFrame, product_type: str) -> float:
    """Equal-weighted mean L1 base_rate over the PBs and products of one type.

    Phase 1 has four PBs, so the type's L1 slice must hold 4 × (products in the
    type) rows; any other count means a product, PB or tier is missing from the
    rate file (§2.5). The mean is unweighted across products and PBs, which is
    what lets an equal-weighted unit book reproduce T.
    """
    required = {"pb_id", "product_id", "liquidity_tier", "base_rate"}
    missing = required.difference(rates.columns)
    if missing:
        raise ValueError(f"rates are missing required columns: {', '.join(sorted(missing))}")
    if "product_type" not in products.columns:
        raise ValueError("products are missing required column: product_type")

    product_ids = products.loc[products["product_type"].eq(product_type), "product_id"]
    if product_ids.empty:
        raise ValueError(f"no products with product_type {product_type!r}")
    if product_ids.duplicated().any():
        raise ValueError(f"products must hold one row per product_id; {product_type!r} repeats one")

    l1 = rates.loc[rates["product_id"].isin(product_ids) & rates["liquidity_tier"].eq("L1")]
    expected = 4 * int(product_ids.nunique())
    if len(l1) != expected:
        raise ValueError(
            f"expected {expected} L1 rate rows for {product_type!r} "
            f"(4 PBs × {product_ids.nunique()} products); got {len(l1)}"
        )
    values = pd.to_numeric(l1["base_rate"], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"L1 base_rate for {product_type!r} must be finite numeric values")
    return float(values.mean())


CALIBRATED_COLUMNS = [
    "pb_id",
    "product_id",
    "liquidity_tier",
    "product_type",
    "base_rate_phase1",
    "k_t",
    "base_rate_cal",
    "financing_spread_bps",
    "phi",
]


def calibrate_rates(
    rates: pd.DataFrame,
    products: pd.DataFrame,
    targets: dict,
    proxy_buckets: dict,
    vol_multipliers: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scale every Phase 1 base rate to its type's target (§2.5–§2.6).

    For type t, k_t = T_t / (vol_mult[b_t] · R_t) with R_t from
    ``reference_rate``, and base_rate_cal = k_t · base_rate on every row. One
    scalar per type means every within-type relativity (product, PB, tier) is
    preserved exactly. Returns the calibrated rows, one per input rate row, and
    a product_type / R_t / k_t scalar table.
    """
    key = ["pb_id", "product_id", "liquidity_tier"]
    required = {*key, "base_rate", "financing_spread_bps", "phi"}
    missing = required.difference(rates.columns)
    if missing:
        raise ValueError(f"rates are missing required columns: {', '.join(sorted(missing))}")
    if "product_type" not in products.columns:
        raise ValueError("products are missing required column: product_type")
    for name, mapping in (
        ("targets", targets),
        ("proxy_buckets", proxy_buckets),
        ("vol_multipliers", vol_multipliers),
    ):
        if not isinstance(mapping, dict):
            raise TypeError(f"{name} must be a dict")

    product_types = products[["product_id", "product_type"]]
    if product_types["product_id"].duplicated().any():
        raise ValueError("products must hold one row per product_id")
    merged = rates.merge(product_types, on="product_id", how="inner", validate="many_to_one")
    if len(merged) != len(rates):
        unmatched = sorted(set(rates["product_id"]) - set(products["product_id"]))
        raise ValueError(f"rates rows lost joining products; unmatched product_id: {unmatched}")
    if merged["product_type"].isna().any():
        raise ValueError("products are missing product_type for some product_id")
    if merged.duplicated(key).any():
        raise ValueError("rates must hold one row per (pb_id, product_id, liquidity_tier)")

    scalar_rows = []
    for product_type in sorted(str(value) for value in merged["product_type"].unique()):
        if product_type not in targets:
            raise ValueError(f"missing target for product_type {product_type!r}")
        if product_type not in proxy_buckets:
            raise ValueError(f"missing proxy bucket for product_type {product_type!r}")
        bucket = proxy_buckets[product_type]
        if bucket not in vol_multipliers:
            raise ValueError(f"no volatility multiplier for bucket {bucket!r} ({product_type!r})")
        multiplier = float(vol_multipliers[bucket])
        target = float(targets[product_type])
        if not np.isfinite(multiplier) or multiplier <= 0.0 or not np.isfinite(target):
            raise ValueError(f"invalid multiplier or target for product_type {product_type!r}")
        r_t = reference_rate(rates, products, product_type)
        scalar_rows.append(
            {"product_type": product_type, "R_t": r_t, "k_t": target / (multiplier * r_t)}
        )
    scalars = pd.DataFrame(scalar_rows, columns=["product_type", "R_t", "k_t"])

    calibrated = merged.rename(columns={"base_rate": "base_rate_phase1"}).copy()
    calibrated["k_t"] = calibrated["product_type"].map(scalars.set_index("product_type")["k_t"])
    calibrated["base_rate_cal"] = calibrated["k_t"] * calibrated["base_rate_phase1"]
    calibrated = calibrated[CALIBRATED_COLUMNS].reset_index(drop=True)
    if len(calibrated) != len(rates):
        raise ValueError("calibrated rates did not keep one row per input rate row")
    if calibrated[["k_t", "base_rate_cal"]].isna().any().any():
        raise ValueError("some product types had no k_t mapping")
    return calibrated, scalars


# === Pipeline (AI-assisted, spec §3–§5) ===

def month_end_dates(index, start: str = "2019-01", end: str = "2026-09") -> pd.DatetimeIndex:
    """Return last available observation in each month in the inclusive range."""
    dates = pd.DatetimeIndex(pd.to_datetime(index)).dropna().normalize().sort_values().unique()
    if not len(dates):
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    frame = pd.DataFrame({"date": dates})
    frame["month"] = frame["date"].dt.to_period("M")
    first, last = pd.Period(start, freq="M"), pd.Period(end, freq="M")
    frame = frame.loc[frame["month"].between(first, last)]
    return pd.DatetimeIndex(frame.groupby("month", sort=True)["date"].max().to_numpy())


def test_windows(prices: pd.Series, d_m: pd.Timestamp, h: int) -> pd.DataFrame:
    """Build non-overlapping complete h-day blocks in the following month."""
    if h < 1:
        raise ValueError("h must be positive")
    values = pd.to_numeric(prices, errors="coerce").dropna().astype(float).sort_index()
    values.index = pd.DatetimeIndex(pd.to_datetime(values.index)).normalize()
    d_m = pd.Timestamp(d_m).normalize()
    next_month = d_m.to_period("M") + 1
    month_dates = values.index[(values.index > d_m) & (values.index.to_period("M") == next_month)]
    rows = []
    previous = float(values.loc[d_m]) if d_m in values.index else None
    for offset in range(0, len(month_dates) - h + 1, h):
        block = month_dates[offset : offset + h]
        start_price = previous if offset == 0 else float(values.loc[month_dates[offset - 1]])
        end_price = float(values.loc[block[-1]])
        if start_price <= 0 or end_price <= 0:
            raise ValueError("prices must be positive")
        rows.append({"start": block[0], "end": block[-1], "return": math.log(end_price) - math.log(start_price)})
    return pd.DataFrame(rows, columns=["start", "end", "return"])


def kupiec(n: int, x: int, p: float = 0.01) -> tuple[float, float]:
    """Kupiec proportion-of-failures LR and chi-square(1) p-value."""
    n, x, p = int(n), int(x), float(p)
    if n < 0 or x < 0 or x > n or not 0 < p < 1:
        raise ValueError("require n >= x >= 0 and 0 < p < 1")
    if n == 0:
        return 0.0, 1.0
    def xlog(value: float, base: float) -> float:
        return 0.0 if value == 0 else value * math.log(base)
    ll_null = xlog(n - x, 1 - p) + xlog(x, p)
    phat = x / n
    ll_alt = xlog(n - x, 1 - phat) + xlog(x, phat)
    lr = max(0.0, -2.0 * (ll_null - ll_alt))
    return lr, math.erfc(math.sqrt(lr / 2.0))


def _binomial_cdf(n: int, x: int, p: float) -> float:
    if x < 0:
        return 0.0
    if x >= n:
        return 1.0
    # Recurrence from P(X=0), stable for the small tail counts used here.
    term = (1.0 - p) ** n
    total = term
    for k in range(1, x + 1):
        term *= ((n - k + 1) / k) * (p / (1.0 - p))
        total += term
    return min(1.0, total)


def traffic_light(n: int, x: int, p: float = 0.01) -> str:
    """Generalised Basel traffic light from the binomial cumulative rule."""
    cdf = _binomial_cdf(int(n), int(x), float(p))
    if cdf < 0.95:
        return "green"
    if cdf < 0.9999:
        return "yellow"
    return "red"


def _load_proxy_returns(raw_dir: Path, proxy: pd.Series) -> tuple[pd.Series, pd.Series]:
    from .calib_data import dgs10_price_returns, log_returns, price_index_from_returns

    symbol = str(proxy["proxy_symbol"])
    frame = pd.read_csv(Path(raw_dir) / f"{symbol}.csv", parse_dates=["date"])
    if proxy["return_type"] == "dgs10_price_return":
        duration = float(proxy["duration"])
        returns = dgs10_price_returns(frame, duration)
    else:
        returns = log_returns(frame)
    returns.index = pd.DatetimeIndex(returns.index)
    prices = price_index_from_returns(returns)
    return returns, prices


def run_targets(case: Case, raw_dir: Path, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Estimate point-in-time APC targets and Phase 1 mapping scalars by type."""
    from .calib_data import dgs10_price_returns, log_returns, price_index_from_returns

    proxies = pd.read_csv(Path(__file__).resolve().parents[2] / "data/public/calibration_proxies.csv")
    products = case.raw_tables["products"]
    date = pd.Timestamp(as_of or case.params["as_of_date"])
    rows = []
    # Read a price-series proxy first; the core call then stops cleanly until
    # Kakali implements the registered return-risk routines.
    for proxy in proxies.sort_values("product_type", kind="mergesort").to_dict("records"):
        frame = pd.read_csv(Path(raw_dir) / f"{proxy['proxy_symbol']}.csv", parse_dates=["date"])
        if proxy["return_type"] == "dgs10_price_return":
            frame.attrs.update(return_type="dgs10_price_return", duration=float(proxy["duration"]))
            daily = dgs10_price_returns(frame, float(proxy["duration"]))
        else:
            daily = log_returns(frame)
        h = int(proxy["mpor_days"])
        h_returns = h_day_returns(daily, h)
        recent = es_recent(h_returns, date)
        stress, stress_end = es_stress(h_returns, date)
        target, floor_binding = apc_target(float(recent["es"]), float(stress))
        proxy_prices = price_index_from_returns(daily.loc[daily.index <= date])
        bucket = vol_bucket(
            proxy_prices,
            date,
            float(case.params["vol_cut_low"]),
            float(case.params["vol_cut_high"]),
        )
        rows.append({
            "product_type": proxy["product_type"], "proxy": proxy["proxy_symbol"], "h": h,
            "n_recent": recent["n"], "ES_recent_long": recent["long"],
            "ES_recent_short": recent["short"], "ES_recent": recent["es"],
            "ES_stress": stress, "stress_window_end": stress_end,
            "floor_binding": floor_binding, "T": target, "b_t": bucket,
        })
    target_by_type = {row["product_type"]: row["T"] for row in rows}
    buckets = {row["product_type"]: row["b_t"] for row in rows}
    vol_mult = {"V1": case.params["vol_mult_v1"], "V2": case.params["vol_mult_v2"], "V3": case.params["vol_mult_v3"]}
    calibrated, scalars = calibrate_rates(case.rates, products, target_by_type, buckets, vol_mult)
    scalar_by_type = scalars.set_index("product_type")
    for row in rows:
        row["R_t"] = scalar_by_type.loc[row["product_type"], "R_t"]
        row["k_t"] = scalar_by_type.loc[row["product_type"], "k_t"]
    return pd.DataFrame(rows), calibrated


BACKTEST_COLUMNS = [
    "product_type", "side", "apc", "n", "exceedances", "rate",
    "kupiec_lr", "kupiec_p", "zone",
]


def _backtest_month(
    h_returns: pd.Series,
    prices: pd.Series,
    d_m: pd.Timestamp,
    h: int,
) -> pd.DataFrame:
    """Return this month's non-overlapping side/APC exceedance counts."""
    recent = es_recent(h_returns, d_m)
    stress, _ = es_stress(h_returns, d_m)
    target_apc, _ = apc_target(float(recent["es"]), float(stress))
    windows = test_windows(prices, d_m, h)
    window_returns = windows["return"].to_numpy(dtype=float)
    rows = []
    for side, losses in (
        ("long", -window_returns),
        ("short", window_returns),
    ):
        for apc, target in ((True, target_apc), (False, float(recent["es"]))):
            rows.append({
                "side": side,
                "apc": apc,
                "n": int(len(losses)),
                "exceedances": int(np.sum(losses > float(target))),
            })
    return pd.DataFrame(rows, columns=["side", "apc", "n", "exceedances"])


def _aggregate_backtest_months(monthly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly counts before computing coverage statistics."""
    required = {"product_type", "side", "apc", "n", "exceedances"}
    missing = required.difference(monthly.columns)
    if missing:
        raise ValueError(f"monthly backtest rows missing columns: {', '.join(sorted(missing))}")
    aggregated = monthly.groupby(["product_type", "side", "apc"], as_index=False, sort=True)[
        ["n", "exceedances"]
    ].sum()
    aggregated["rate"] = aggregated["exceedances"] / aggregated["n"].replace(0, np.nan)
    diagnostics = [kupiec(int(row.n), int(row.exceedances)) for row in aggregated.itertuples()]
    aggregated["kupiec_lr"] = [values[0] for values in diagnostics]
    aggregated["kupiec_p"] = [values[1] for values in diagnostics]
    aggregated["zone"] = [
        traffic_light(int(n), int(x))
        for n, x in zip(aggregated["n"], aggregated["exceedances"], strict=True)
    ]
    return aggregated[BACKTEST_COLUMNS].sort_values(
        ["product_type", "side", "apc"], kind="mergesort"
    ).reset_index(drop=True)


def run_backtest(case: Case, raw_dir: Path, out_dir: Path) -> pd.DataFrame:
    """Aggregate walk-forward exceedances across all 93 months per test case."""
    proxies = pd.read_csv(Path(__file__).resolve().parents[2] / "data/public/calibration_proxies.csv")
    monthly_rows = []
    for proxy in proxies.to_dict("records"):
        daily, prices = _load_proxy_returns(Path(raw_dir), pd.Series(proxy))
        h = int(proxy["mpor_days"])
        # Each proxy's overlapping return series is invariant across the dates.
        h_returns = h_day_returns(daily, h)
        for date in month_end_dates(prices.index):
            counts = _backtest_month(h_returns, prices, date, h)
            counts.insert(0, "product_type", proxy["product_type"])
            monthly_rows.append(counts)
    monthly = pd.concat(monthly_rows, ignore_index=True) if monthly_rows else pd.DataFrame(
        columns=["product_type", "side", "apc", "n", "exceedances"]
    )
    frame = _aggregate_backtest_months(monthly)
    write_csv(frame, Path(out_dir) / "backtest.csv")
    return frame


def _two_sided_tail(returns: pd.Series | np.ndarray, alpha: float, statistic: str) -> float:
    """Return the worse-side ES or VaR using Kakali's es_var primitive."""
    values = np.asarray(returns, dtype=float).reshape(-1)
    long_es, long_var = es_var(-values, alpha)
    short_es, short_var = es_var(values, alpha)
    if statistic == "ES":
        return max(float(long_es), float(short_es))
    if statistic == "VaR":
        return max(float(long_var), float(short_var))
    raise ValueError("statistic must be 'ES' or 'VaR'")


def _rolling_two_sided_tail(
    h_returns: pd.Series,
    d: pd.Timestamp,
    alpha: float,
    statistic: str,
    window: int = 250,
) -> float:
    """Maximum two-sided ES or VaR over complete point-in-time windows."""
    available = pd.to_numeric(h_returns.loc[h_returns.index <= pd.Timestamp(d)], errors="coerce")
    values = available.to_numpy(dtype=float)
    if len(values) < window:
        raise ValueError(f"need at least {window} returns for the stressed statistic")
    return max(
        _two_sided_tail(values[start : start + window], alpha, statistic)
        for start in range(0, len(values) - window + 1)
    )


def _apc_driver_rows(
    h_returns: pd.Series,
    d: pd.Timestamp,
    recent: dict | None = None,
    stress: float | None = None,
) -> list[dict[str, object]]:
    """Return the four APC alternatives, all against the same ES 97.5 base."""
    if recent is None:
        recent = es_recent(h_returns, d)
    if stress is None:
        stress, _ = es_stress(h_returns, d)
    es_recent_value = float(recent["es"])
    base_target, _ = apc_target(es_recent_value, float(stress))
    ten_year = h_returns.loc[
        (h_returns.index > pd.Timestamp(d) - pd.DateOffset(years=10))
        & (h_returns.index <= pd.Timestamp(d))
    ]
    es_ten_year = _two_sided_tail(ten_year, 0.975, "ES")
    return [
        {"driver": "APC", "setting": "none", "es_recent": es_recent_value, "T": es_recent_value},
        {"driver": "APC", "setting": "25% stressed weight with floor", "es_recent": es_recent_value, "T": base_target},
        {"driver": "APC", "setting": "25% buffer", "es_recent": es_recent_value, "T": 1.25 * es_recent_value},
        {"driver": "APC", "setting": "10-year lookback floor", "es_recent": es_recent_value,
         "T": max(es_recent_value, es_ten_year)},
    ]


DRIVER_COLUMNS = [
    "driver", "setting", "es_recent", "T", "pb_id", "pre_buffer_unit_margin",
    "exchange_pct", "ratio",
]


def run_drivers(
    case: Case,
    raw_dir: Path,
    targets: pd.DataFrame,
    calibrated_rates: pd.DataFrame,
    out_dir: Path,
) -> pd.DataFrame:
    """Run one-at-a-time IRSF drivers and compare calibrated ZN unit margins."""
    proxy = pd.read_csv(Path(__file__).resolve().parents[2] / "data/public/calibration_proxies.csv")
    proxy_row = proxy.loc[proxy["product_type"].eq("irs_proxy_future")].iloc[0]
    daily, _ = _load_proxy_returns(Path(raw_dir), proxy_row)
    d = pd.Timestamp(case.params["as_of_date"])
    returns_by_h = {h: h_day_returns(daily, h) for h in (1, 2, 5)}
    base_returns = returns_by_h[2]
    base_recent = es_recent(base_returns, d)
    base_stress, _ = es_stress(base_returns, d)
    base_recent_value = float(base_recent["es"])
    base_target, _ = apc_target(base_recent_value, float(base_stress))
    rows: list[dict[str, object]] = []

    rows.append({"driver": "confidence", "setting": "ES 97.5 (base)",
                 "es_recent": base_recent_value, "T": base_target})
    two_year = base_returns.loc[
        (base_returns.index > d - pd.DateOffset(years=2)) & (base_returns.index <= d)
    ]
    var_recent = _two_sided_tail(two_year, 0.99, "VaR")
    var_stress = _rolling_two_sided_tail(base_returns, d, 0.99, "VaR")
    var_target, _ = apc_target(var_recent, var_stress)
    rows.append({"driver": "confidence", "setting": "VaR 99",
                 "es_recent": var_recent, "T": var_target})
    es99_recent = es_recent(base_returns, d, alpha=0.99)
    es99_stress = _rolling_two_sided_tail(base_returns, d, 0.99, "ES")
    es99_target, _ = apc_target(float(es99_recent["es"]), es99_stress)
    rows.append({"driver": "confidence", "setting": "ES 99",
                 "es_recent": float(es99_recent["es"]), "T": es99_target})

    for h in (1, 2, 5):
        if h == 2:
            recent_h, stress_h = base_recent, float(base_stress)
        else:
            recent_h = es_recent(returns_by_h[h], d)
            stress_h, _ = es_stress(returns_by_h[h], d)
        target_h, _ = apc_target(float(recent_h["es"]), float(stress_h))
        rows.append({"driver": "MPOR", "setting": f"{h} trading days" + (" (base)" if h == 2 else ""),
                     "es_recent": float(recent_h["es"]), "T": target_h})

    for years in (1.0, 2.0, 5.0):
        recent_y = base_recent if years == 2.0 else es_recent(base_returns, d, years=years)
        target_y, _ = apc_target(float(recent_y["es"]), float(base_stress))
        rows.append({"driver": "lookback", "setting": f"{years:g} years" + (" (base)" if years == 2.0 else ""),
                     "es_recent": float(recent_y["es"]), "T": target_y})

    rows.extend(_apc_driver_rows(base_returns, d, base_recent, float(base_stress)))

    one_day_recent = es_recent(returns_by_h[1], d)
    one_day_stress, _ = es_stress(returns_by_h[1], d)
    one_day_target, _ = apc_target(float(one_day_recent["es"]), float(one_day_stress))
    rows.extend([
        {"driver": "scaling", "setting": "overlapping h=2 (base)",
         "es_recent": base_recent_value, "T": base_target},
        {"driver": "scaling", "setting": "sqrt(2) × 1-day",
         "es_recent": math.sqrt(2) * float(one_day_recent["es"]), "T": math.sqrt(2) * one_day_target},
    ])

    exchange = pd.read_csv(Path(__file__).resolve().parents[2] / "data/public/exchange_margin.csv")
    zn = exchange.loc[exchange["product_id"].eq("IRSF_10Y")].iloc[0]
    exchange_pct = float(zn["initial_margin_usd"]) / (float(zn["settle_price"]) * float(zn["multiplier"]))
    buckets = case.book.loc[case.book["product_id"].eq("IRSF_10Y"), "vol_bucket"].dropna().unique()
    if len(buckets) != 1:
        raise ValueError("IRSF_10Y positions must have one Phase 1 vol_bucket for the ZN comparison")
    phase1_bucket = str(buckets[0])
    vol_multiplier = float(case.params["vol_multipliers"][phase1_bucket])
    irsf_rates = calibrated_rates.loc[
        calibrated_rates["product_id"].eq("IRSF_10Y")
        & calibrated_rates["liquidity_tier"].eq("L1")
    ]
    for item in irsf_rates.sort_values("pb_id", kind="mergesort").itertuples(index=False):
        unit_margin = float(item.base_rate_cal) * vol_multiplier
        rows.append({
            "driver": "ZN comparison", "setting": f"{item.pb_id} at Phase 1 bucket {phase1_bucket}",
            "es_recent": np.nan, "T": np.nan, "pb_id": item.pb_id,
            "pre_buffer_unit_margin": unit_margin, "exchange_pct": exchange_pct,
            "ratio": unit_margin / exchange_pct if exchange_pct else np.nan,
        })
    frame = pd.DataFrame(rows).reindex(columns=DRIVER_COLUMNS)
    write_csv(frame, Path(out_dir) / "drivers_irsf.csv")
    return frame


def _calibration_slacks(
    book: pd.DataFrame,
    weights: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    borrow: pd.DataFrame,
    params: object,
) -> dict[str, float]:
    """Recompute positive capacity, counterparty and locate shortfalls."""
    notional = book["notional_usd"].to_numpy(dtype=float)
    gross = notional @ weights
    capacity = providers["capacity_usd"].to_numpy(dtype=float)
    capacity_slack = float(np.maximum(0.0, gross - capacity).sum())
    margin = margin_by_pb(book, weights, rates, providers, params)["margin_usd"].to_numpy(dtype=float)
    limits = providers["counterparty_limit_usd"].to_numpy(dtype=float)
    counterparty_slack = float(np.maximum(0.0, margin - limits).sum())

    located = (
        book["side"].lt(0).to_numpy()
        & book["needs_locate"].astype("boolean").fillna(False).to_numpy(dtype=bool)
    )
    available = borrow.set_index(["pb_id", "issuer_id"])["borrow_available_usd"]
    borrow_slack = 0.0
    for col, pb_id in enumerate(providers["pb_id"].tolist()):
        for issuer in book.loc[located, "issuer_id"].dropna().unique():
            row_ids = np.flatnonzero(located & book["issuer_id"].eq(issuer).to_numpy())
            used = float(notional[row_ids] @ weights[row_ids, col])
            borrow_slack += max(0.0, used - float(available.get((pb_id, issuer), 0.0)))
    return {
        "capacity": 0.0 if capacity_slack <= 1e-6 else capacity_slack,
        "counterparty": 0.0 if counterparty_slack <= 1e-6 else counterparty_slack,
        "borrow": 0.0 if borrow_slack <= 1e-6 else borrow_slack,
    }


def _phase1_weights(case: Case, run_dir: Path) -> np.ndarray:
    allocation = pd.read_csv(Path(run_dir) / "results/positions_alloc.csv")
    matrix = allocation.pivot(index="pos_id", columns="pb_id", values="w")
    matrix = matrix.reindex(index=case.book["pos_id"], columns=case.providers["pb_id"])
    if matrix.isna().any().any():
        raise ValueError("run_42 allocation does not cover the loaded positions and PBs")
    return matrix.to_numpy(dtype=float)


def _moves_between(
    book: pd.DataFrame,
    phase1_weights: np.ndarray,
    calibrated_weights: np.ndarray,
    pb_ids: list[object],
) -> pd.DataFrame:
    """Match per-position PB outflows to inflows, as in Phase 2a moves."""
    notional = book["notional_usd"].to_numpy(dtype=float)
    records = []
    for row, pos_id in enumerate(book["pos_id"].tolist()):
        difference = calibrated_weights[row] - phase1_weights[row]
        difference[np.abs(difference) <= 1e-9] = 0.0
        outflow = notional[row] * np.maximum(0.0, -difference)
        inflow = notional[row] * np.maximum(0.0, difference)
        for from_col, from_pb in enumerate(pb_ids):
            for to_col, to_pb in enumerate(pb_ids):
                if from_col == to_col:
                    continue
                moved = min(outflow[from_col], inflow[to_col])
                if moved >= 1e-6:
                    records.append({
                        "scenario": "calibrated", "pos_id": pos_id,
                        "from_pb": from_pb, "to_pb": to_pb,
                        "notional_moved_usd": float(moved),
                    })
                    outflow[from_col] -= moved
                    inflow[to_col] -= moved
    columns = ["scenario", "pos_id", "from_pb", "to_pb", "notional_moved_usd"]
    return pd.DataFrame(records, columns=columns).sort_values(
        ["scenario", "pos_id", "from_pb", "to_pb"], kind="mergesort"
    ).reset_index(drop=True)


def _constraint_snapshot(
    case: Case,
    weights: np.ndarray,
    rates: pd.DataFrame,
    duals: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build SQL-30-constraints-shaped use/slack/dual data for one allocation."""
    book, providers, borrow = case.book, case.providers, case.borrow
    notional = book["notional_usd"].to_numpy(dtype=float)
    gross = notional @ weights
    margins = margin_by_pb(book, weights, rates, providers, case.params).set_index("pb_id")["margin_usd"]
    rows: list[dict[str, object]] = []

    def append(block: str, pb_id: object, issuer_id: object, limit: float, used: float) -> None:
        slack = float(limit) - float(used)
        binding = slack <= 1e-6 * max(1.0, float(limit))
        dual_frame = duals.get(block, pd.DataFrame())
        key_cols = ["pb_id"] + (["issuer_id"] if block == "borrow" else [])
        dual_value = np.nan
        if len(dual_frame) and set(key_cols + ["dual_usd_per_usd"]).issubset(dual_frame.columns):
            match = dual_frame
            for key in key_cols:
                match = match.loc[match[key].eq(pb_id if key == "pb_id" else issuer_id)]
            if len(match):
                dual_value = float(match.iloc[0]["dual_usd_per_usd"])
        rows.append({"block": block, "pb_id": pb_id, "issuer_id": issuer_id,
                     "limit_usd": float(limit), "used_usd": float(used), "slack_usd": slack,
                     "binding": bool(binding), "dual_usd_per_usd": dual_value})

    for col, row in enumerate(providers.itertuples(index=False)):
        append("capacity", row.pb_id, np.nan, row.capacity_usd, gross[col])
        append("counterparty", row.pb_id, np.nan, row.counterparty_limit_usd, margins.loc[row.pb_id])

    located = book["side"].lt(0) & book["needs_locate"].astype("boolean").fillna(False)
    for item in borrow.itertuples(index=False):
        mask = located & book["issuer_id"].eq(item.issuer_id)
        row_ids = np.flatnonzero(mask.to_numpy())
        pb_col = providers["pb_id"].tolist().index(item.pb_id)
        used = float(notional[row_ids] @ weights[row_ids, pb_col]) if len(row_ids) else 0.0
        append("borrow", item.pb_id, item.issuer_id, item.borrow_available_usd, used)
    return pd.DataFrame(rows, columns=[
        "block", "pb_id", "issuer_id", "limit_usd", "used_usd", "slack_usd", "binding", "dual_usd_per_usd",
    ]).sort_values(["block", "pb_id", "issuer_id"], kind="mergesort", na_position="last").reset_index(drop=True)


def _compare_constraints(phase1: pd.DataFrame, calibrated: pd.DataFrame) -> pd.DataFrame:
    keys = ["block", "pb_id", "issuer_id"]
    left = phase1.rename(columns={
        "limit_usd": "limit_phase1_usd", "used_usd": "used_phase1_usd",
        "slack_usd": "slack_phase1_usd", "binding": "binding_phase1",
        "dual_usd_per_usd": "dual_phase1_usd_per_usd",
    })
    right = calibrated.rename(columns={
        "limit_usd": "limit_calibrated_usd", "used_usd": "used_calibrated_usd",
        "slack_usd": "slack_calibrated_usd", "binding": "binding_calibrated",
        "dual_usd_per_usd": "dual_calibrated_usd_per_usd",
    })
    for frame in (left, right):
        frame["issuer_id"] = frame["issuer_id"].fillna("").astype(str)
    return left.merge(right, on=keys, how="outer", validate="one_to_one").sort_values(
        keys, kind="mergesort", na_position="last"
    ).reset_index(drop=True)


def run_calibrated_case(case: Case, calibrated_rates: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Re-run allocation and PM pass-through on a copy, compared with run_42."""
    repo = Path(__file__).resolve().parents[2]
    run_dir = repo / "reports" / "run_42"
    working = case.book.copy(deep=True)
    rates = case.rates.copy(deep=True)
    key = ["pb_id", "product_id", "liquidity_tier"]
    if "base_rate_cal" not in calibrated_rates:
        raise ValueError("calibrated rates require base_rate_cal")
    rates = rates.merge(calibrated_rates[key + ["base_rate_cal"]], on=key, validate="one_to_one")
    rates["base_rate"] = rates.pop("base_rate_cal")
    result = optimise(working, rates, case.providers.copy(deep=True), case.borrow.copy(deep=True), case.params.copy())
    weights = np.asarray(result.w, dtype=float)
    margin = margin_by_pb(working, weights, rates, case.providers, case.params)
    total_margin = float(margin["margin_usd"].sum())
    slack = _calibration_slacks(working, weights, rates, case.providers, case.borrow, case.params)
    total_slack = float(sum(slack.values()))
    if result.status == "optimal":
        if total_slack > 1e-6:
            raise RuntimeError("calibrated allocation is optimal but recomputed slack is nonzero")
        slack = {key: 0.0 for key in slack}
        total_slack = 0.0

    phase1_summary = pd.read_csv(run_dir / "results/run_summary.csv").iloc[0]
    financing = float(result.financing_usd)
    margin_funding = float(result.margin_funding_usd)
    summary = pd.DataFrame([{
        "status": str(result.status),
        "total_margin_usd": total_margin,
        "delta_total_margin_usd": total_margin - float(phase1_summary["total_margin_usd"]),
        "financing_cost_usd": financing,
        "delta_financing_cost_usd": financing - float(phase1_summary["financing_usd"])
        if np.isfinite(financing) else np.nan,
        "margin_funding_cost_usd": margin_funding,
        "delta_margin_funding_cost_usd": margin_funding - float(phase1_summary["margin_funding_usd"])
        if np.isfinite(margin_funding) else np.nan,
        "slack_capacity_usd": slack["capacity"],
        "slack_counterparty_usd": slack["counterparty"],
        "slack_borrow_usd": slack["borrow"],
        "total_slack_usd": total_slack,
    }])

    calibrated_pm = attribute(
        working, weights, rates, case.providers, case.params, pm_ids=case.pms["pm_id"].tolist()
    )
    phase1_pm = pd.read_csv(run_dir / "results/attribution.csv")[["pm_id", "charge_usd"]].rename(
        columns={"charge_usd": "charge_phase1"}
    )
    charges = phase1_pm.merge(
        calibrated_pm[["pm_id", "charge_usd", "attributed_margin_usd"]].rename(columns={
            "charge_usd": "charge_calibrated",
            "attributed_margin_usd": "attributed_margin_calibrated_usd",
        }), on="pm_id", validate="one_to_one",
    )
    charges["delta"] = charges["charge_calibrated"] - charges["charge_phase1"]
    charges["rank_phase1"] = charges["charge_phase1"].rank(method="min", ascending=False).astype(int)
    charges["rank_calibrated"] = charges["charge_calibrated"].rank(method="min", ascending=False).astype(int)
    charges["rank_change"] = charges["rank_calibrated"] - charges["rank_phase1"]
    charges = charges[[
        "pm_id", "charge_phase1", "charge_calibrated", "delta", "rank_phase1", "rank_calibrated",
        "rank_change", "attributed_margin_calibrated_usd",
    ]].sort_values("pm_id", kind="mergesort").reset_index(drop=True)

    phase1_weights = _phase1_weights(case, run_dir)
    moves = _moves_between(working, phase1_weights, weights, case.providers["pb_id"].tolist())
    phase1_constraints = pd.read_csv(run_dir / "tables/30_constraints.csv")
    calibrated_constraints = _constraint_snapshot(case, weights, rates, result.duals)
    binding = _compare_constraints(phase1_constraints, calibrated_constraints)
    return {
        "calib_summary": summary,
        "calib_pm_charges": charges,
        "calib_moves": moves,
        "calib_binding": binding,
    }


def run_calibration(case: Case, raw_dir: Path, out_dir: Path) -> dict[str, pd.DataFrame]:
    """Run calibration, backtest, drivers and portfolio re-run under out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    targets, calibrated = run_targets(case, Path(raw_dir))
    write_csv(targets, out / "calibration_targets.csv")
    write_csv(calibrated, out / "calibrated_rates.csv")
    backtest = run_backtest(case, Path(raw_dir), out)
    drivers = run_drivers(case, Path(raw_dir), targets, calibrated, out)
    scenario = run_calibrated_case(case, calibrated)
    for name, frame in scenario.items():
        write_csv(frame, out / f"{name}.csv")
    return {"targets": targets, "backtest": backtest, "drivers": drivers, **scenario}
