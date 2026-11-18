"""Linear-programming allocation optimiser for the M2 model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import cvxpy as cp
import numpy as np
import pandas as pd

from .margin import Index, build_index, margin_by_pb


@dataclass(frozen=True)
class Result:
    """Allocation, cost, margin, and constraint diagnostics from M2."""

    status: str
    w: np.ndarray
    objective_usd: float
    financing_usd: float
    margin_funding_usd: float
    margin_by_pb: pd.DataFrame
    duals: dict[str, pd.DataFrame]
    slack_blocks: set[str]
    solver_margin_by_pb: np.ndarray


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


def _bool_column(book: pd.DataFrame, name: str) -> np.ndarray:
    if name not in book:
        raise ValueError(f"book is missing required column: {name}")
    try:
        return book[name].astype("boolean").fillna(False).to_numpy(dtype=bool)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"book column {name} must contain boolean values") from exc


def funding_rates(
    book: pd.DataFrame,
    rates: pd.DataFrame,
    borrow: pd.DataFrame,
    pb_ids: object,
) -> tuple[np.ndarray, np.ndarray]:
    """Return funding costs in bps and the position/PB locate mask.

    Longs and shorts that do not need a locate pay the PB's financing spread.
    A short that needs a locate pays that PB/issuer's borrow fee and is allowed
    only where a positive borrow amount is available.
    """
    if not isinstance(book, pd.DataFrame):
        raise TypeError("book must be a pandas DataFrame")
    if not isinstance(rates, pd.DataFrame) or not isinstance(borrow, pd.DataFrame):
        raise TypeError("rates and borrow must be pandas DataFrames")
    pb_order = tuple(pb_ids["pb_id"].tolist()) if isinstance(pb_ids, pd.DataFrame) else tuple(pb_ids)
    if len(set(pb_order)) != len(pb_order):
        raise ValueError("pb_ids must be unique")

    required_book = {"pos_id", "product_id", "liquidity_tier", "side", "notional_usd", "issuer_id"}
    missing = required_book.difference(book.columns)
    if missing:
        raise ValueError(f"book is missing required columns: {', '.join(sorted(missing))}")
    needs_locate = _bool_column(book, "needs_locate")
    sides = book["side"].to_numpy(dtype=float)
    short_needs_locate = (sides < 0) & needs_locate

    rate_columns = {"pb_id", "product_id", "liquidity_tier", "financing_spread_bps"}
    missing = rate_columns.difference(rates.columns)
    if missing:
        raise ValueError(f"rates are missing required columns: {', '.join(sorted(missing))}")
    rate_keys = ["pb_id", "product_id", "liquidity_tier"]
    if rates.duplicated(rate_keys).any():
        raise ValueError("rates must have one row per (pb_id, product_id, liquidity_tier)")

    borrow_columns = {"pb_id", "issuer_id", "borrow_fee_bps", "borrow_available_usd"}
    missing = borrow_columns.difference(borrow.columns)
    if missing:
        raise ValueError(f"borrow is missing required columns: {', '.join(sorted(missing))}")
    borrow_keys = ["pb_id", "issuer_id"]
    if borrow.duplicated(borrow_keys).any():
        raise ValueError("borrow must have one row per (pb_id, issuer_id)")

    n_pos, n_pb = len(book), len(pb_order)
    k = np.empty((n_pos, n_pb), dtype=float)
    allowed = np.ones((n_pos, n_pb), dtype=bool)
    keyed = book[["product_id", "liquidity_tier"]].reset_index(drop=True)
    for col, pb_id in enumerate(pb_order):
        pb_rates = rates.loc[
            rates["pb_id"].eq(pb_id),
            ["product_id", "liquidity_tier", "financing_spread_bps"],
        ]
        aligned_rates = keyed.merge(
            pb_rates,
            on=["product_id", "liquidity_tier"],
            how="left",
            validate="many_to_one",
            sort=False,
        )
        if aligned_rates["financing_spread_bps"].isna().any():
            raise ValueError(f"missing financing rate rows at {pb_id}")
        k[:, col] = aligned_rates["financing_spread_bps"].to_numpy(dtype=float)

        allowed[short_needs_locate, col] = False
        located_positions = np.flatnonzero(short_needs_locate & book["issuer_id"].notna().to_numpy())
        if not len(located_positions):
            continue
        issuer_rows = book.iloc[located_positions][["issuer_id"]].reset_index(drop=True)
        pb_borrow = borrow.loc[
            borrow["pb_id"].eq(pb_id),
            ["issuer_id", "borrow_fee_bps", "borrow_available_usd"],
        ]
        aligned_borrow = issuer_rows.merge(
            pb_borrow,
            on="issuer_id",
            how="left",
            validate="many_to_one",
            sort=False,
        )
        available = aligned_borrow["borrow_available_usd"].fillna(0.0).to_numpy(dtype=float)
        has_locate = available > 0.0
        if np.any(has_locate & aligned_borrow["borrow_fee_bps"].isna().to_numpy()):
            raise ValueError(f"missing borrow fee at {pb_id}")
        positions_with_locate = located_positions[has_locate]
        allowed[positions_with_locate, col] = True
        k[positions_with_locate, col] = aligned_borrow.loc[
            has_locate, "borrow_fee_bps"
        ].to_numpy(dtype=float)

    no_allowed = np.flatnonzero(~allowed.any(axis=1))
    if len(no_allowed):
        pos_id = book.iloc[int(no_allowed[0])]["pos_id"]
        raise ValueError(f"position {pos_id} has no allowed PB")
    if not np.isfinite(k).all():
        raise ValueError("funding rates must be finite")
    return k, allowed


def _borrow_constraints(
    book: pd.DataFrame,
    borrow: pd.DataFrame,
    pb_ids: tuple[object, ...],
) -> list[tuple[object, object, np.ndarray, float]]:
    """Return allowed borrow-capacity rows in stable PB/issuer order."""
    needs_locate = _bool_column(book, "needs_locate")
    short_located = (book["side"].to_numpy(dtype=float) < 0) & needs_locate
    short_located &= book["issuer_id"].notna().to_numpy()
    short_rows = np.flatnonzero(short_located)
    if not len(short_rows):
        return []

    borrow_lookup = borrow.set_index(["pb_id", "issuer_id"])
    short_book = pd.DataFrame(
        {
            "issuer_id": book.iloc[short_rows]["issuer_id"].to_numpy(),
            "row_position": short_rows,
        }
    )
    groups = short_book.groupby("issuer_id", sort=False)
    rows_by_issuer = {
        issuer_id: group["row_position"].to_numpy(dtype=int)
        for issuer_id, group in groups
    }
    result: list[tuple[object, object, np.ndarray, float]] = []
    for pb_id in pb_ids:
        for issuer_id, rows in rows_by_issuer.items():
            key = (pb_id, issuer_id)
            if key not in borrow_lookup.index:
                continue
            available = float(borrow_lookup.loc[key, "borrow_available_usd"])
            if available > 0.0:
                result.append((pb_id, issuer_id, rows, available))
    return result


def _make_duals(
    pb_ids: tuple[object, ...],
    borrow_rows: list[tuple[object, object, np.ndarray, float]],
    capacity_constraint: cp.Constraint,
    counterparty_constraint: cp.Constraint,
    borrow_constraints: list[cp.Constraint],
) -> dict[str, pd.DataFrame]:
    capacity_dual = np.asarray(capacity_constraint.dual_value, dtype=float).reshape(-1)
    counterparty_dual = np.asarray(counterparty_constraint.dual_value, dtype=float).reshape(-1)
    borrow_values = [float(np.asarray(item.dual_value).reshape(-1)[0]) for item in borrow_constraints]
    return {
        "capacity": pd.DataFrame(
            {"pb_id": pb_ids, "dual_usd_per_usd": capacity_dual}
        ),
        "counterparty": pd.DataFrame(
            {"pb_id": pb_ids, "dual_usd_per_usd": counterparty_dual}
        ),
        "borrow": pd.DataFrame(
            [
                {"pb_id": pb_id, "issuer_id": issuer_id, "dual_usd_per_usd": dual}
                for (pb_id, issuer_id, _, _), dual in zip(borrow_rows, borrow_values, strict=True)
            ],
            columns=["pb_id", "issuer_id", "dual_usd_per_usd"],
        ),
    }


def optimise(
    book: pd.DataFrame,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    borrow: pd.DataFrame,
    params: object,
    ell_bps: float | None = None,
) -> Result:
    """Minimize funding cost plus margin funding under M2 constraints.

    A nominally infeasible allocation problem is solved a second time with
    nonnegative USD slacks on capacity, counterparty, and borrow blocks. The
    returned status remains ``infeasible`` and ``slack_blocks`` identifies
    blocks whose minimum slack exceeds one micro-dollar. For infeasible
    results, ``w`` and ``margin_by_pb`` show the slack solution, while costs
    are NaN and duals are empty because the slack-only objective has no cost
    interpretation for the original problem.
    """
    if not isinstance(book, pd.DataFrame) or not isinstance(providers, pd.DataFrame):
        raise TypeError("book and providers must be pandas DataFrames")
    provider_columns = {
        "pb_id",
        "capacity_usd",
        "counterparty_limit_usd",
        "conc_threshold",
        "conc_rate",
    }
    missing = provider_columns.difference(providers.columns)
    if missing:
        raise ValueError(f"providers are missing required columns: {', '.join(sorted(missing))}")
    if providers["pb_id"].duplicated().any():
        raise ValueError("providers must have one row per pb_id")

    pb_ids = tuple(providers["pb_id"].tolist())
    n_pos, n_pb = len(book), len(pb_ids)
    notional = book["notional_usd"].to_numpy(dtype=float)
    side = book["side"].to_numpy(dtype=float)
    k, allowed = funding_rates(book, rates, borrow, pb_ids)
    vol_multipliers = _param(params, "vol_multipliers")
    house_buffer = float(_param(params, "house_buffer"))
    horizon_days = float(_param(params, "horizon_days"))
    if ell_bps is None:
        ell_bps = float(_param(params, "liquidity_premium_bps"))
    else:
        ell_bps = float(ell_bps)
    if not np.isfinite([house_buffer, horizon_days, ell_bps]).all():
        raise ValueError("house_buffer, horizon_days, and ell_bps must be finite")

    index: Index = build_index(book, providers, rates, vol_multipliers)
    family_count = len(index.family_rows)
    issuer_count = len(index.issuer_rows)
    family_notionals = np.zeros((family_count, n_pos), dtype=float)
    family_signed = np.zeros((family_count, n_pos), dtype=float)
    for family_no, rows in enumerate(index.family_rows):
        family_notionals[family_no, rows] = notional[rows]
        family_signed[family_no, rows] = side[rows] * notional[rows]
    issuer_notionals = np.zeros((issuer_count, n_pos), dtype=float)
    for issuer_no, rows in enumerate(index.issuer_rows):
        issuer_notionals[issuer_no, rows] = notional[rows]

    family_r = (
        np.vstack([index.r[rows[0], :] for rows in index.family_rows])
        if family_count
        else np.zeros((0, n_pb), dtype=float)
    )
    family_phi = (
        np.vstack([index.phi[rows[0], :] for rows in index.family_rows])
        if family_count
        else np.zeros((0, n_pb), dtype=float)
    )
    provider_theta = providers["conc_threshold"].to_numpy(dtype=float)
    provider_conc_rate = providers["conc_rate"].to_numpy(dtype=float)
    capacity = providers["capacity_usd"].to_numpy(dtype=float)
    counterparty_limit = providers["counterparty_limit_usd"].to_numpy(dtype=float)
    borrow_rows = _borrow_constraints(book, borrow, pb_ids)
    borrow_pb_cols = np.array([pb_ids.index(row[0]) for row in borrow_rows], dtype=int)
    borrow_issuer_rows = [row[2] for row in borrow_rows]
    borrow_available = np.array([row[3] for row in borrow_rows], dtype=float)

    funding_scale = horizon_days * 1e-4 / 360.0
    margin_scale = ell_bps * 1e-4 * horizon_days / 360.0
    funding_coefficients = notional[:, None] * k * funding_scale
    pb_gross_coefficients = notional[:, None]

    def build_and_solve(with_slacks: bool):
        w = cp.Variable((n_pos, n_pb), nonneg=True, name="w")
        constraints: list[cp.Constraint] = [cp.sum(w, axis=1) == 1.0]
        if (~allowed).any():
            constraints.append(w[~allowed] == 0.0)

        gross_by_pb = cp.sum(cp.multiply(pb_gross_coefficients, w), axis=0)
        family_margin_by_pb: cp.Expression
        if family_count:
            gross_by_family = family_notionals @ w
            signed_by_family = family_signed @ w
            abs_net = cp.Variable((family_count, n_pb), nonneg=True, name="family_net")
            constraints.extend([abs_net >= signed_by_family, abs_net >= -signed_by_family])
            fm = cp.multiply(
                family_r,
                cp.multiply(family_phi, abs_net)
                + cp.multiply(1.0 - family_phi, gross_by_family),
            )
            family_margin_by_pb = cp.sum(fm, axis=0)
        else:
            family_margin_by_pb = cp.Constant(np.zeros(n_pb, dtype=float))

        if issuer_count:
            gross_by_issuer = issuer_notionals @ w
            addon_epigraph = cp.Variable((issuer_count, n_pb), nonneg=True, name="conc_addon")
            threshold_by_pb = cp.multiply(provider_theta, gross_by_pb)
            constraints.append(addon_epigraph >= gross_by_issuer - threshold_by_pb)
            conc_margin_by_pb = cp.multiply(
                provider_conc_rate, cp.sum(addon_epigraph, axis=0)
            )
        else:
            addon_epigraph = None
            conc_margin_by_pb = cp.Constant(np.zeros(n_pb, dtype=float))

        margin_expression = house_buffer * (family_margin_by_pb + conc_margin_by_pb)
        capacity_slack = counterparty_slack = borrow_slack = None
        if with_slacks:
            capacity_slack = cp.Variable(n_pb, nonneg=True, name="capacity_slack")
            counterparty_slack = cp.Variable(n_pb, nonneg=True, name="counterparty_slack")
            capacity_constraint = gross_by_pb <= capacity + capacity_slack
            counterparty_constraint = margin_expression <= counterparty_limit + counterparty_slack
            constraints.extend([capacity_constraint, counterparty_constraint])
            if len(borrow_rows):
                borrow_slack = cp.Variable(len(borrow_rows), nonneg=True, name="borrow_slack")
        else:
            capacity_constraint = gross_by_pb <= capacity
            counterparty_constraint = margin_expression <= counterparty_limit
            constraints.extend([capacity_constraint, counterparty_constraint])

        borrow_exposure = []
        for rows, pb_col in zip(borrow_issuer_rows, borrow_pb_cols, strict=True):
            borrow_exposure.append(
                cp.sum(cp.multiply(notional[rows], w[rows, int(pb_col)]))
            )
        borrow_constraints: list[cp.Constraint] = []
        if borrow_exposure:
            for row_no, exposure in enumerate(borrow_exposure):
                if with_slacks:
                    assert borrow_slack is not None
                    borrow_constraint = exposure <= borrow_available[row_no] + borrow_slack[row_no]
                else:
                    borrow_constraint = exposure <= borrow_available[row_no]
                constraints.append(borrow_constraint)
                borrow_constraints.append(borrow_constraint)

        financing_expression = cp.sum(cp.multiply(funding_coefficients, w))
        if with_slacks:
            slack_terms = [cp.sum(capacity_slack), cp.sum(counterparty_slack)]
            if borrow_slack is not None:
                slack_terms.append(cp.sum(borrow_slack))
            objective = cp.Minimize(sum(slack_terms))
        else:
            objective = cp.Minimize(financing_expression + margin_scale * cp.sum(margin_expression))
        problem = cp.Problem(objective, constraints)
        problem.solve(solver="HIGHS", canon_backend=cp.SCIPY_CANON_BACKEND)
        return {
            "problem": problem,
            "w": w,
            "margin": margin_expression,
            "capacity_constraint": capacity_constraint,
            "counterparty_constraint": counterparty_constraint,
            "borrow_constraints": borrow_constraints,
            "capacity_slack": capacity_slack,
            "counterparty_slack": counterparty_slack,
            "borrow_slack": borrow_slack,
        }

    solved = build_and_solve(with_slacks=False)
    solver_status = str(solved["problem"].status)
    slack_blocks: set[str] = set()
    if solver_status == cp.INFEASIBLE:
        solved = build_and_solve(with_slacks=True)
        slack_status = str(solved["problem"].status)
        if slack_status != cp.OPTIMAL:
            raise RuntimeError(f"slack re-solve failed with status {slack_status}")
        for block_name, slack in (
            ("capacity", solved["capacity_slack"]),
            ("counterparty", solved["counterparty_slack"]),
            ("borrow", solved["borrow_slack"]),
        ):
            if slack is not None and np.any(np.asarray(slack.value) > 1e-6):
                slack_blocks.add(block_name)
    elif solver_status != cp.OPTIMAL:
        raise RuntimeError(f"optimisation failed with status {solver_status}")

    weights = np.clip(np.asarray(solved["w"].value, dtype=float), 0.0, None)
    reported_margin = margin_by_pb(book, weights, rates, providers, params)
    solver_margin = np.asarray(solved["margin"].value, dtype=float).reshape(-1)
    if solver_status == cp.OPTIMAL:
        financing_usd = float(np.sum(notional[:, None] * weights * k) * funding_scale)
        margin_funding_usd = float(reported_margin["margin_usd"].sum() * margin_scale)
        objective_usd = financing_usd + margin_funding_usd
        solver_objective = float(solved["problem"].value)
        if abs(objective_usd - solver_objective) > 1e-6 * max(1.0, abs(solver_objective)):
            raise RuntimeError(
                f"recomputed objective {objective_usd} != solver {solver_objective}"
            )
        duals = _make_duals(
            pb_ids,
            borrow_rows,
            solved["capacity_constraint"],
            solved["counterparty_constraint"],
            solved["borrow_constraints"],
        )
    else:
        objective_usd = float("nan")
        financing_usd = float("nan")
        margin_funding_usd = float("nan")
        duals = {}
    return Result(
        status=solver_status,
        w=weights,
        objective_usd=objective_usd,
        financing_usd=financing_usd,
        margin_funding_usd=margin_funding_usd,
        margin_by_pb=reported_margin,
        duals=duals,
        slack_blocks=slack_blocks,
        solver_margin_by_pb=solver_margin,
    )

