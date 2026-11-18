"""Numerical implementation of the M1 margin proxy.

Allocation matrices use position rows and provider columns. Provider columns
are always in the order supplied by the ``providers`` frame.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import numpy as np
import pandas as pd


FAMILY_COLUMNS = ("product_id", "liquidity_tier", "vol_bucket")
FAMILY_DETAIL_COLUMNS = (
    "pb_id",
    "product_id",
    "liquidity_tier",
    "vol_bucket",
    "gross_usd",
    "net_usd",
    "r",
    "phi",
    "margin_usd",
)
ISSUER_DETAIL_COLUMNS = (
    "pb_id",
    "issuer_id",
    "issuer_gross_usd",
    "pb_gross_usd",
    "threshold_usd",
    "conc_rate",
    "addon_usd",
)


@dataclass(frozen=True)
class Index:
    """Reusable row index for family and concentration calculations."""

    pb_ids: tuple[object, ...]
    family_keys: tuple[tuple[object, object, object], ...]
    family_rows: tuple[np.ndarray, ...]
    issuer_ids: tuple[object, ...]
    issuer_rows: tuple[np.ndarray, ...]
    r: np.ndarray | None = None
    phi: np.ndarray | None = None


def vol_bucket(
    closes: pd.Series,
    as_of: object,
    cut_low: float = 0.10,
    cut_high: float = 0.20,
) -> str:
    """Return a volatility bucket from closes through ``as_of``.

    The annualized sample volatility uses the latest 60 close-to-close log
    returns (``ddof=1``). Fewer than 60 returns, including fewer than 61
    usable closes, maps to V3. Values below ``cut_low`` are V1; values from
    ``cut_low`` through ``cut_high`` inclusive are V2; higher values are V3.
    """
    if cut_low < 0 or cut_high < cut_low:
        raise ValueError("cutoffs must satisfy 0 <= cut_low <= cut_high")
    if not isinstance(closes, pd.Series):
        closes = pd.Series(closes)

    values = pd.to_numeric(closes, errors="coerce").dropna()
    if not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any():
        raise ValueError("closes must contain finite, positive values")
    if not isinstance(values.index, pd.DatetimeIndex):
        try:
            values.index = pd.to_datetime(values.index)
        except (TypeError, ValueError) as exc:
            raise ValueError("closes must have a date-like index") from exc
    cutoff = pd.Timestamp(as_of)
    # Comparing timezone-aware and naive timestamps raises; normalize both to
    # naive UTC because dates in the input data represent market close dates.
    if values.index.tz is not None:
        values.index = values.index.tz_convert("UTC").tz_localize(None)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("UTC").tz_localize(None)
    values = values.loc[values.index <= cutoff].sort_index()
    returns = np.log(values).diff().dropna().tail(60)
    if len(returns) < 60:
        return "V3"
    annualized_vol = float(returns.std(ddof=1) * np.sqrt(252.0))
    if annualized_vol < cut_low:
        return "V1"
    if annualized_vol <= cut_high:
        return "V2"
    return "V3"


def family_margin(r: float, phi: float, gross: float, net: float) -> float:
    """Compute family margin before concentration add-ons and house buffer."""
    return float(r * (phi * net + (1.0 - phi) * gross))


def validate_rates(rates: pd.DataFrame) -> None:
    """Reject rates with invalid base rates or offset fractions.

    The error identifies the first offending (PB, product, tier) row so the
    loader can report the problematic source record.
    """
    if not isinstance(rates, pd.DataFrame):
        raise TypeError("rates must be a pandas DataFrame")
    required = {"pb_id", "product_id", "liquidity_tier", "base_rate", "phi"}
    missing = required.difference(rates.columns)
    if missing:
        raise ValueError(f"rates are missing required columns: {', '.join(sorted(missing))}")
    base_rate = pd.to_numeric(rates["base_rate"], errors="coerce").to_numpy(dtype=float)
    phi = pd.to_numeric(rates["phi"], errors="coerce").to_numpy(dtype=float)
    invalid = (
        ~np.isfinite(base_rate)
        | (base_rate <= 0.0)
        | ~np.isfinite(phi)
        | (phi < 0.0)
        | (phi >= 1.0)
    )
    bad_rows = np.flatnonzero(invalid)
    if len(bad_rows):
        row = rates.iloc[int(bad_rows[0])]
        key = (row["pb_id"], row["product_id"], row["liquidity_tier"])
        raise ValueError(f"invalid base_rate or phi for (pb_id, product_id, liquidity_tier) {key!r}")


def _provider_ids(pbs: object) -> tuple[object, ...]:
    if isinstance(pbs, pd.DataFrame):
        if "pb_id" not in pbs:
            raise ValueError("providers must contain a pb_id column")
        values = tuple(pbs["pb_id"].tolist())
    elif isinstance(pbs, pd.Series):
        values = tuple(pbs.tolist())
    else:
        values = tuple(pbs)  # type: ignore[arg-type]
    if len(set(values)) != len(values):
        raise ValueError("provider pb_id values must be unique")
    return values


def build_index(
    book: pd.DataFrame,
    pbs: object,
    rates: pd.DataFrame | None = None,
    vol_multipliers: object = None,
) -> Index:
    """Build stable family/issuer row groups and, when supplied, rate arrays.

    ``r`` and ``phi`` are position-by-PB arrays aligned with the returned PB
    order. The optional inputs keep the structural index usable on its own.
    """
    missing = [column for column in FAMILY_COLUMNS if column not in book.columns]
    if missing:
        raise ValueError(f"book is missing required columns: {', '.join(missing)}")
    pb_ids = _provider_ids(pbs)
    family_keys: list[tuple[object, object, object]] = []
    family_rows: list[np.ndarray] = []
    if len(book):
        grouped = book.groupby(list(FAMILY_COLUMNS), sort=False, dropna=False).indices
        for key, rows in grouped.items():
            family_keys.append(tuple(key))
            family_rows.append(np.asarray(rows, dtype=int))

    issuer_ids: list[object] = []
    issuer_rows: list[np.ndarray] = []
    if {"issuer_id", "conc_eligible"}.issubset(book.columns):
        eligible = (
            book["conc_eligible"].astype("boolean").fillna(False).to_numpy(dtype=bool)
            & book["issuer_id"].notna().to_numpy()
        )
        eligible_positions = np.flatnonzero(eligible)
        eligible_book = book.loc[eligible, ["issuer_id"]].reset_index(drop=True)
        for issuer_id, rows in eligible_book.groupby("issuer_id", sort=False).indices.items():
            issuer_ids.append(issuer_id)
            issuer_rows.append(eligible_positions[np.asarray(rows, dtype=int)])
    rate_array = phi_array = None
    if rates is not None:
        if vol_multipliers is None:
            raise ValueError("params missing vol_multipliers")
        rate_array, phi_array = _aligned_rates(book, rates, pb_ids, vol_multipliers)
    return Index(
        pb_ids=pb_ids,
        family_keys=tuple(family_keys),
        family_rows=tuple(family_rows),
        issuer_ids=tuple(issuer_ids),
        issuer_rows=tuple(issuer_rows),
        r=rate_array,
        phi=phi_array,
    )


def _mapping(value: object, key: str) -> object:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
    else:
        marker = object()
        result = getattr(value, key, marker)
        if result is not marker:
            return result
    raise ValueError(f"params missing {key}")


def _aligned_rates(
    book: pd.DataFrame,
    rates: pd.DataFrame,
    pb_ids: tuple[object, ...],
    multipliers: object,
) -> tuple[np.ndarray, np.ndarray]:
    required_rates = {"pb_id", "product_id", "liquidity_tier", "base_rate", "phi"}
    missing = required_rates.difference(rates.columns)
    if missing:
        raise ValueError(f"rates are missing required columns: {', '.join(sorted(missing))}")
    keys = ["pb_id", "product_id", "liquidity_tier"]
    if rates.duplicated(keys).any():
        raise ValueError("rates must have one row per (pb_id, product_id, liquidity_tier)")
    if "vol_bucket" not in book:
        raise ValueError("book must contain vol_bucket")

    n_pos, n_pb = len(book), len(pb_ids)
    r_values = np.empty((n_pos, n_pb), dtype=float)
    phi_values = np.empty((n_pos, n_pb), dtype=float)
    keyed = book[["product_id", "liquidity_tier", "vol_bucket"]].reset_index(drop=True)
    multiplier = keyed["vol_bucket"].map(multipliers)
    if multiplier.isna().any():
        raise ValueError("no volatility multiplier for some vol_bucket values")
    for col, pb_id in enumerate(pb_ids):
        pb_rates = rates.loc[
            rates["pb_id"].eq(pb_id),
            ["product_id", "liquidity_tier", "base_rate", "phi"],
        ]
        aligned = keyed.merge(
            pb_rates,
            on=["product_id", "liquidity_tier"],
            how="left",
            validate="many_to_one",
            sort=False,
        )
        if aligned[["base_rate", "phi"]].isna().any().any():
            raise ValueError(f"missing rate rows at {pb_id}")
        r_values[:, col] = aligned["base_rate"].to_numpy(dtype=float) * multiplier.to_numpy(dtype=float)
        phi_values[:, col] = aligned["phi"].to_numpy(dtype=float)
    return r_values, phi_values


def _evaluate(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not isinstance(book, pd.DataFrame):
        raise TypeError("book must be a pandas DataFrame")
    if not isinstance(providers, pd.DataFrame):
        raise TypeError("providers must be a pandas DataFrame")
    if not {"pb_id", "conc_threshold", "conc_rate"}.issubset(providers.columns):
        raise ValueError("providers must contain pb_id, conc_threshold, and conc_rate")
    multipliers = _mapping(params, "vol_multipliers")
    house_buffer = float(_mapping(params, "house_buffer"))
    index = build_index(book, providers, rates, multipliers)
    weights = np.asarray(w, dtype=float)
    expected_shape = (len(book), len(index.pb_ids))
    if weights.shape != expected_shape:
        raise ValueError(f"w must have shape {expected_shape}; received {weights.shape}")
    if not np.isfinite(weights).all():
        raise ValueError("w must contain only finite values")

    assert index.r is not None and index.phi is not None
    r, phi = index.r, index.phi

    family_records: list[dict[str, object]] = []
    family_margin_by_pb = np.zeros(len(index.pb_ids), dtype=float)
    for family_key, rows in zip(index.family_keys, index.family_rows, strict=True):
        product_id, tier, bucket = family_key
        family_book = book.iloc[rows]
        notionals = family_book["notional_usd"].to_numpy(dtype=float)
        sides = family_book["side"].to_numpy(dtype=float)
        for col, pb_id in enumerate(index.pb_ids):
            position_weights = weights[rows, col]
            gross = float(np.dot(notionals, position_weights))
            net = float(abs(np.dot(sides * notionals, position_weights)))
            family_r = float(r[rows[0], col])
            family_phi = float(phi[rows[0], col])
            margin = family_margin(family_r, family_phi, gross, net)
            family_margin_by_pb[col] += margin
            family_records.append(
                {
                    "pb_id": pb_id,
                    "product_id": product_id,
                    "liquidity_tier": tier,
                    "vol_bucket": bucket,
                    "gross_usd": gross,
                    "net_usd": net,
                    "r": family_r,
                    "phi": family_phi,
                    "margin_usd": margin,
                }
            )

    pb_gross = (book["notional_usd"].to_numpy(dtype=float)[:, None] * weights).sum(axis=0)
    provider_lookup = providers.set_index("pb_id")
    issuer_records: list[dict[str, object]] = []
    addon_by_pb = np.zeros(len(index.pb_ids), dtype=float)
    for issuer_id, rows in zip(index.issuer_ids, index.issuer_rows, strict=True):
        notionals = book.iloc[rows]["notional_usd"].to_numpy(dtype=float)
        issuer_gross_by_pb = (notionals[:, None] * weights[rows, :]).sum(axis=0)
        for col, pb_id in enumerate(index.pb_ids):
            provider = provider_lookup.loc[pb_id]
            threshold = float(provider["conc_threshold"]) * float(pb_gross[col])
            concentration_rate = float(provider["conc_rate"])
            addon = concentration_rate * max(0.0, float(issuer_gross_by_pb[col]) - threshold)
            addon_by_pb[col] += addon
            issuer_records.append(
                {
                    "pb_id": pb_id,
                    "issuer_id": issuer_id,
                    "issuer_gross_usd": float(issuer_gross_by_pb[col]),
                    "pb_gross_usd": float(pb_gross[col]),
                    "threshold_usd": threshold,
                    "conc_rate": concentration_rate,
                    "addon_usd": addon,
                }
            )

    pb_records = [
        {
            "pb_id": pb_id,
            "margin_usd": float(house_buffer * (family_margin_by_pb[col] + addon_by_pb[col])),
        }
        for col, pb_id in enumerate(index.pb_ids)
    ]
    return (
        pd.DataFrame(pb_records, columns=["pb_id", "margin_usd"]),
        pd.DataFrame(family_records, columns=FAMILY_DETAIL_COLUMNS),
        pd.DataFrame(issuer_records, columns=ISSUER_DETAIL_COLUMNS),
    )


def _margin_vector(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    index: Index | None = None,
) -> np.ndarray:
    """Compute buffered margin by PB with NumPy, optionally reusing an index.

    A supplied index must be built from the same book rows and volatility
    buckets, rates, and providers. It may be reused when only notionals change;
    changes to rows or buckets require rebuilding it.
    """
    if not isinstance(book, pd.DataFrame):
        raise TypeError("book must be a pandas DataFrame")
    if not isinstance(providers, pd.DataFrame):
        raise TypeError("providers must be a pandas DataFrame")
    if not {"pb_id", "conc_threshold", "conc_rate"}.issubset(providers.columns):
        raise ValueError("providers must contain pb_id, conc_threshold, and conc_rate")
    pb_ids = _provider_ids(providers)
    if index is None:
        multipliers = _mapping(params, "vol_multipliers")
        index = build_index(book, providers, rates, multipliers)
    else:
        if index.pb_ids != pb_ids:
            raise ValueError("prebuilt index PB order does not match providers")
        if index.r is None or index.phi is None:
            raise ValueError("prebuilt index must include r and phi arrays")
        expected_rate_shape = (len(book), len(pb_ids))
        if index.r.shape != expected_rate_shape or index.phi.shape != expected_rate_shape:
            raise ValueError(
                f"prebuilt index rate arrays must have shape {expected_rate_shape}"
            )

    weights = np.asarray(w, dtype=float)
    expected_shape = (len(book), len(pb_ids))
    if weights.shape != expected_shape:
        raise ValueError(f"w must have shape {expected_shape}; received {weights.shape}")
    if not np.isfinite(weights).all():
        raise ValueError("w must contain only finite values")
    required_book = {"notional_usd", "side"}
    missing = required_book.difference(book.columns)
    if missing:
        raise ValueError(f"book is missing required columns: {', '.join(sorted(missing))}")

    notionals = book["notional_usd"].to_numpy(dtype=float)
    sides = book["side"].to_numpy(dtype=float)
    exposure = notionals[:, None] * weights
    signed_exposure = (sides * notionals)[:, None] * weights
    family_margin_by_pb = np.zeros(len(pb_ids), dtype=float)
    assert index.r is not None and index.phi is not None
    for rows in index.family_rows:
        r0 = index.r[rows[0]]
        phi0 = index.phi[rows[0]]
        family_margin_by_pb += r0 * (
            phi0 * np.abs(signed_exposure[rows].sum(axis=0))
            + (1.0 - phi0) * exposure[rows].sum(axis=0)
        )

    pb_gross = exposure.sum(axis=0)
    provider_theta = providers["conc_threshold"].to_numpy(dtype=float)
    provider_conc_rate = providers["conc_rate"].to_numpy(dtype=float)
    addon_by_pb = np.zeros(len(pb_ids), dtype=float)
    for rows in index.issuer_rows:
        issuer_gross = exposure[rows].sum(axis=0)
        addon_by_pb += provider_conc_rate * np.maximum(
            0.0, issuer_gross - provider_theta * pb_gross
        )

    house_buffer = float(_mapping(params, "house_buffer"))
    return house_buffer * (family_margin_by_pb + addon_by_pb)


def margin_by_pb(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    index: Index | None = None,
) -> pd.DataFrame:
    """Return buffered margin by PB; a matching prebuilt index may be reused."""
    values = _margin_vector(book, w, rates, providers, params, index=index)
    return pd.DataFrame({"pb_id": _provider_ids(providers), "margin_usd": values})


def total_margin(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    index: Index | None = None,
) -> float:
    """Return total buffered margin, reusing an optional matching index."""
    return float(_margin_vector(book, w, rates, providers, params, index=index).sum())


def margin_detail(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return family-level and eligible-issuer-level margin detail."""
    _, family_df, issuer_df = _evaluate(book, w, rates, providers, params)
    return family_df, issuer_df

