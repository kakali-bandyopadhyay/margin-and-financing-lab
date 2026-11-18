"""M3 prime-broker margin usage and illustrative PM charge attribution."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .margin import Index, build_index, total_margin


def _param(params: object, name: str) -> object:
    if isinstance(params, Mapping):
        if name in params:
            return params[name]
    else:
        marker = object()
        value = getattr(params, name, marker)
        if value is not marker:
            return value
    raise ValueError(f"params missing {name}")


def pm_usage(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    pm_ids: object = None,
    index: Index | None = None,
) -> tuple[pd.DataFrame, float]:
    """Return fixed-allocation leave-one-out usage, solo margin, and total M.

    Each evaluation uses a copy of the fixed allocation. The index is built
    once and reused for the full book and all PM counterfactuals.
    """
    if not isinstance(book, pd.DataFrame):
        raise TypeError("book must be a pandas DataFrame")
    if "pm_id" not in book:
        raise ValueError("book is missing required column: pm_id")
    weights = np.asarray(w, dtype=float)
    if weights.ndim != 2 or weights.shape[0] != len(book):
        raise ValueError("w must have one row per book position")
    if not np.isfinite(weights).all():
        raise ValueError("w must contain only finite values")

    if pm_ids is None:
        pm_values = book["pm_id"].dropna().unique().tolist()
    else:
        pm_values = list(pm_ids)
    if len(set(pm_values)) != len(pm_values):
        raise ValueError("pm_ids must be unique")
    pm_values = sorted(pm_values)

    if index is None:
        multipliers = _param(params, "vol_multipliers")
        index = build_index(book, providers, rates, multipliers)

    full_margin = total_margin(book, weights, rates, providers, params, index=index)
    records: list[dict[str, object]] = []
    book_pms = book["pm_id"]
    for pm_id in pm_values:
        is_pm = book_pms.eq(pm_id).to_numpy()

        without_pm = weights.copy()
        without_pm[is_pm, :] = 0.0
        remaining_margin = total_margin(
            book, without_pm, rates, providers, params, index=index
        )

        solo_weights = np.zeros_like(weights)
        solo_weights[is_pm, :] = weights[is_pm, :]
        solo_margin = total_margin(book, solo_weights, rates, providers, params, index=index)
        records.append(
            {
                "pm_id": pm_id,
                "usage_usd": full_margin - remaining_margin,
                "solo_margin_usd": solo_margin,
            }
        )

    usage_df = pd.DataFrame(
        records,
        columns=["pm_id", "usage_usd", "solo_margin_usd"],
    )
    return usage_df, full_margin


def attribute_pm_usage(
    usage: Mapping[object, float],
    solo_margin: Mapping[object, float],
    total_margin: float,
    pass_through_bps: float,
    horizon_days: float,
) -> pd.DataFrame:
    """Allocate the residual by solo-margin share and calculate PM charges."""
    if set(usage) != set(solo_margin):
        raise ValueError("usage and solo_margin must have the same PM keys")

    pm_ids = sorted(usage)
    usage_values = {pm_id: float(usage[pm_id]) for pm_id in pm_ids}
    solo_values = {pm_id: float(solo_margin[pm_id]) for pm_id in pm_ids}
    if any(not np.isfinite(value) for value in usage_values.values()):
        raise ValueError("usage values must be finite")
    if any(not np.isfinite(value) for value in solo_values.values()):
        raise ValueError("solo_margin values must be finite")
    if any(value < -1e-9 for value in solo_values.values()):
        raise ValueError("solo_margin values must be non-negative")

    total_margin = float(total_margin)
    pass_through_bps = float(pass_through_bps)
    horizon_days = float(horizon_days)
    if not np.isfinite([total_margin, pass_through_bps, horizon_days]).all():
        raise ValueError("total_margin, pass_through_bps, and horizon_days must be finite")

    residual = total_margin - sum(usage_values.values())
    nonnegative_solo = {pm_id: max(0.0, value) for pm_id, value in solo_values.items()}
    solo_total = sum(nonnegative_solo.values())
    if solo_total == 0.0:
        if abs(residual) > 1e-9:
            raise ValueError("zero solo-margin denominator with non-zero residual")
        shares = {pm_id: 0.0 for pm_id in pm_ids}
    else:
        shares = {
            pm_id: nonnegative_solo[pm_id] / solo_total
            for pm_id in pm_ids
        }

    charge_scale = pass_through_bps * 1e-4 * horizon_days / 360.0
    records = []
    for pm_id in pm_ids:
        residual_share = shares[pm_id] * residual
        attributed = usage_values[pm_id] + residual_share
        records.append(
            {
                "pm_id": pm_id,
                "usage_usd": usage_values[pm_id],
                "solo_margin_usd": solo_values[pm_id],
                "share": shares[pm_id],
                "residual_usd": residual_share,
                "attributed_margin_usd": attributed,
                "charge_usd": attributed * charge_scale,
            }
        )
    result = pd.DataFrame(
        records,
        columns=[
            "pm_id",
            "usage_usd",
            "solo_margin_usd",
            "share",
            "residual_usd",
            "attributed_margin_usd",
            "charge_usd",
        ],
    )
    if abs(float(result["attributed_margin_usd"].sum()) - total_margin) > 1e-6:
        raise RuntimeError("attributed PM margins do not sum to total margin")
    return result


def attribute(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    pm_ids: object = None,
    index: Index | None = None,
) -> pd.DataFrame:
    """Compute PM usage, solo shares, residual allocations, and charges."""
    usage_df, full_margin = pm_usage(
        book,
        w,
        rates,
        providers,
        params,
        pm_ids=pm_ids,
        index=index,
    )
    return attribute_pm_usage(
        usage=usage_df.set_index("pm_id")["usage_usd"].to_dict(),
        solo_margin=usage_df.set_index("pm_id")["solo_margin_usd"].to_dict(),
        total_margin=full_margin,
        pass_through_bps=float(_param(params, "pass_through_bps")),
        horizon_days=float(_param(params, "horizon_days")),
    )

