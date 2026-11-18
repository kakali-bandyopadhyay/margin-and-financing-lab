"""Separate, non-charge M3 exhibits: re-solve, all-in cost, and Euler ranges."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .attribution import pm_usage
from .margin import Index, build_index, margin_by_pb, total_margin
from .optimise import Result, funding_rates, optimise


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


def resolve_usage(
    book: pd.DataFrame,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    borrow: pd.DataFrame,
    params: object,
    base: Result,
) -> pd.DataFrame:
    """Re-solve after removing each PM and report its sensitivity exhibit.

    This function is a separate exhibit and is not used by the charge path.
    """
    if base.status != "optimal":
        raise ValueError("resolve_usage requires an optimal base result")
    usage_df, _ = pm_usage(
        book,
        base.w,
        rates,
        providers,
        params,
    )
    fixed_usage = usage_df.set_index("pm_id")["usage_usd"].to_dict()
    full_margin = float(base.margin_by_pb["margin_usd"].sum())
    records: list[dict[str, object]] = []
    for pm_id in sorted(book["pm_id"].dropna().unique().tolist()):
        keep = book["pm_id"].ne(pm_id).to_numpy()
        remaining = book.loc[keep].reset_index(drop=True)
        remaining_w = base.w[keep, :]
        solved = optimise(remaining, rates, providers, borrow, params)
        if solved.status != "optimal":
            raise RuntimeError(f"re-solve without {pm_id} returned {solved.status}")
        margin_without = total_margin(
            remaining, solved.w, rates, providers, params
        )
        records.append(
            {
                "pm_id": pm_id,
                "status": solved.status,
                "objective_without_usd": solved.objective_usd,
                "delta_objective_usd": base.objective_usd - solved.objective_usd,
                "margin_without_usd": margin_without,
                "usage_resolve_usd": full_margin - margin_without,
                "usage_fixed_usd": fixed_usage[pm_id],
            }
        )
    return pd.DataFrame(
        records,
        columns=[
            "pm_id",
            "status",
            "objective_without_usd",
            "delta_objective_usd",
            "margin_without_usd",
            "usage_resolve_usd",
            "usage_fixed_usd",
        ],
    )


def all_in_cost(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    borrow: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    attributed: pd.DataFrame,
) -> pd.DataFrame:
    """Allocate financing and margin-funding costs to PMs.

    Margin funding uses the liquidity premium ``ell_bps``; it is independent
    of the pass-through charge shown by the attribution module.
    """
    pm_col = book["pm_id"]
    weights = np.asarray(w, dtype=float)
    expected_shape = (len(book), len(providers))
    if weights.shape != expected_shape:
        raise ValueError(f"w must have shape {expected_shape}; received {weights.shape}")
    if not {"pm_id", "attributed_margin_usd"}.issubset(attributed.columns):
        raise ValueError("attributed must contain pm_id and attributed_margin_usd")

    pb_ids = tuple(providers["pb_id"].tolist())
    k, allowed = funding_rates(book, rates, borrow, pb_ids)
    if np.any(np.abs(weights[~allowed]) > 1e-9):
        raise ValueError("w allocates a needs-locate position to a PB with no locate")
    notional = book["notional_usd"].to_numpy(dtype=float)
    scale = float(_param(params, "horizon_days")) * 1e-4 / 360.0
    margin_scale = float(_param(params, "liquidity_premium_bps")) * scale
    margin_by_pm = attributed.set_index("pm_id")["attributed_margin_usd"].to_dict()

    records: list[dict[str, object]] = []
    for pm_id in sorted(pm_col.dropna().unique().tolist()):
        rows = pm_col.eq(pm_id).to_numpy()
        financing = float(np.sum(notional[rows, None] * weights[rows, :] * k[rows, :]) * scale)
        margin_funding = float(margin_by_pm[pm_id]) * margin_scale
        records.append(
            {
                "pm_id": pm_id,
                "financing_usd": financing,
                "margin_funding_usd": margin_funding,
                "all_in_usd": financing + margin_funding,
            }
        )
    return pd.DataFrame(
        records,
        columns=["pm_id", "financing_usd", "margin_funding_usd", "all_in_usd"],
    )


def _matching_index(
    book: pd.DataFrame,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    index: Index | None,
) -> Index:
    if index is None:
        return build_index(book, providers, rates, _param(params, "vol_multipliers"))
    pb_ids = tuple(providers["pb_id"].tolist())
    if index.pb_ids != pb_ids:
        raise ValueError("prebuilt index PB order does not match providers")
    expected_shape = (len(book), len(pb_ids))
    if index.r is None or index.phi is None:
        raise ValueError("prebuilt index must include r and phi arrays")
    if index.r.shape != expected_shape or index.phi.shape != expected_shape:
        raise ValueError(f"prebuilt index rate arrays must have shape {expected_shape}")
    return index


def euler_allocation(
    book: pd.DataFrame,
    w: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    pm_ids: object = None,
    index: Index | None = None,
    rel_tol: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return per-PM Euler values, subgradient ranges, and kink diagnostics.

    At a kink, the point Euler contribution of that term is zero and the
    corresponding low/high range records the valid subgradient choices.
    """
    if not np.isfinite(rel_tol) or rel_tol < 0.0:
        raise ValueError("rel_tol must be finite and non-negative")
    if "pm_id" not in book:
        raise ValueError("book is missing required column: pm_id")
    weights = np.asarray(w, dtype=float)
    pb_ids = tuple(providers["pb_id"].tolist())
    expected_shape = (len(book), len(pb_ids))
    if weights.shape != expected_shape:
        raise ValueError(f"w must have shape {expected_shape}; received {weights.shape}")
    if not np.isfinite(weights).all():
        raise ValueError("w must contain only finite values")
    index = _matching_index(book, rates, providers, params, index)
    assert index.r is not None and index.phi is not None

    if pm_ids is None:
        pm_values = book["pm_id"].dropna().unique().tolist()
    else:
        pm_values = list(pm_ids)
    if len(set(pm_values)) != len(pm_values):
        raise ValueError("pm_ids must be unique")
    pm_values = sorted(pm_values)
    pm_rows = {pm_id: book["pm_id"].eq(pm_id).to_numpy() for pm_id in pm_values}
    point = {pm_id: 0.0 for pm_id in pm_values}
    low = {pm_id: 0.0 for pm_id in pm_values}
    high = {pm_id: 0.0 for pm_id in pm_values}
    notionals = book["notional_usd"].to_numpy(dtype=float)
    sides = book["side"].to_numpy(dtype=float)
    exposure = notionals[:, None] * weights
    signed_exposure = (sides * notionals)[:, None] * weights
    house_buffer = float(_param(params, "house_buffer"))
    kink_records: list[dict[str, object]] = []

    for family_key, rows in zip(index.family_keys, index.family_rows, strict=True):
        for col, pb_id in enumerate(pb_ids):
            gross = float(exposure[rows, col].sum())
            signed = float(signed_exposure[rows, col].sum())
            r0 = float(index.r[rows[0], col])
            phi0 = float(index.phi[rows[0], col])
            net_kink = gross > 0.0 and abs(signed) <= rel_tol * gross
            for pm_id in pm_values:
                selected = rows[pm_rows[pm_id][rows]]
                if not len(selected):
                    continue
                pm_exposure = exposure[selected, col]
                base_family = house_buffer * r0 * (1.0 - phi0) * float(pm_exposure.sum())
                point[pm_id] += base_family
                low[pm_id] += base_family
                high[pm_id] += base_family
                if net_kink:
                    net_component = house_buffer * r0 * phi0 * float(
                        signed_exposure[selected, col].sum()
                    )
                    radius = abs(net_component)
                    low[pm_id] -= radius
                    high[pm_id] += radius
                else:
                    sign = float(np.sign(signed))
                    net_component = house_buffer * r0 * phi0 * sign * float(
                        signed_exposure[selected, col].sum()
                    )
                    point[pm_id] += net_component
                    low[pm_id] += net_component
                    high[pm_id] += net_component
            if net_kink:
                kink_records.append(
                    {
                        "kind": "net",
                        "key": family_key,
                        "pb_id": pb_id,
                        "size_usd": gross,
                        "value_usd": signed,
                    }
                )

    pb_gross = exposure.sum(axis=0)
    theta = providers["conc_threshold"].to_numpy(dtype=float)
    conc_rate = providers["conc_rate"].to_numpy(dtype=float)
    for issuer_id, rows in zip(index.issuer_ids, index.issuer_rows, strict=True):
        is_issuer = np.zeros(len(book), dtype=bool)
        is_issuer[rows] = True
        for col, pb_id in enumerate(pb_ids):
            issuer_gross = float(exposure[rows, col].sum())
            excess = issuer_gross - float(theta[col]) * float(pb_gross[col])
            hinge_kink = (
                issuer_gross > 0.0
                and abs(excess) <= rel_tol * float(pb_gross[col])
            )
            if hinge_kink:
                kink_records.append(
                    {
                        "kind": "hinge",
                        "key": issuer_id,
                        "pb_id": pb_id,
                        "size_usd": issuer_gross,
                        "value_usd": excess,
                    }
                )
            elif excess <= 0.0:
                continue

            for pm_id in pm_values:
                selected = pm_rows[pm_id]
                contribution = house_buffer * float(conc_rate[col]) * float(
                    np.sum((is_issuer[selected].astype(float) - float(theta[col])) * exposure[selected, col])
                )
                if hinge_kink:
                    low[pm_id] += min(0.0, contribution)
                    high[pm_id] += max(0.0, contribution)
                else:
                    point[pm_id] += contribution
                    low[pm_id] += contribution
                    high[pm_id] += contribution

    per_pm = pd.DataFrame(
        [
            {
                "pm_id": pm_id,
                "euler_usd": point[pm_id],
                "euler_low_usd": low[pm_id],
                "euler_high_usd": high[pm_id],
            }
            for pm_id in pm_values
        ],
        columns=["pm_id", "euler_usd", "euler_low_usd", "euler_high_usd"],
    )
    kinks = pd.DataFrame(
        kink_records,
        columns=["kind", "key", "pb_id", "size_usd", "value_usd"],
    )
    return per_pm, kinks

