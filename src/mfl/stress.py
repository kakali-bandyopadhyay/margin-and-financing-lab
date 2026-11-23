"""Phase 2a static prime-broker margin/funding stress projection.

This module implements the scenarios fixed in
``prereg/PREREGISTRATION_PHASE2A.md``.  It reads a Phase 1 :class:`mfl.io.Case`,
re-optimises the book under the pre-registered transforms, and returns the
four result tables plus the supplementary bucket sensitivity.

The module is deliberately self-contained: it does not change any Phase 1
formula or output.  Prices are needed only for the ST1a/ST1b re-bucketing;
they may be supplied directly or found in ``case.raw_tables["price_history"]``
or ``data_dir/price_history.csv``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import cvxpy as cp
import numpy as np
import pandas as pd

from .io import Case
from .margin import margin_by_pb, margin_detail
from .optimise import optimise


SCENARIOS = ("ST0", "ST1a", "ST1b", "ST2a", "ST2b", "ST3", "ST4")
TERMINATION_SCENARIOS = ("ST3", "ST4")

SUMMARY_COLUMNS = (
    "scenario",
    "cost_window_start",
    "total_margin_usd",
    "delta_margin_usd",
    "financing_cost_usd",
    "delta_financing_cost_usd",
    "margin_funding_cost_usd",
    "delta_margin_funding_cost_usd",
    "status",
    "slack_capacity_usd",
    "slack_counterparty_usd",
    "slack_borrow_usd",
    "total_slack_usd",
    "additional_funding_requirement_usd",
    "terminated_pb",
    "notice_days",
    "nav_trigger_pct",
    "notional_to_move_usd",
)
MARGIN_BY_PB_COLUMNS = (
    "scenario",
    "pb_id",
    "margin_usd",
    "gross_usd",
    "capacity_usd",
    "utilisation_pct",
)
MOVES_COLUMNS = ("scenario", "pos_id", "from_pb", "to_pb", "notional_moved_usd")
NETTING_COLUMNS = (
    "scenario",
    "pb_id",
    "role",
    "margin_with_offsets_usd",
    "margin_without_offsets_usd",
    "netting_benefit_usd",
    "st0_margin_with_offsets_usd",
    "st0_margin_without_offsets_usd",
    "st0_netting_benefit_usd",
    "netting_change_usd",
    "reallocation_effect_usd",
    "delta_margin_vs_st0_usd",
    "identity_residual_usd",
)
SENSITIVITY_COLUMNS = (
    "scenario",
    "cut_low",
    "cut_high",
    "total_margin_usd",
    "delta_margin_vs_st0_usd",
    "status",
)


@dataclass(frozen=True)
class StressResult:
    """Tables and allocations returned by :func:`run_scenarios`."""

    summary: pd.DataFrame
    margin_by_pb: pd.DataFrame
    moves: pd.DataFrame
    st3_netting: pd.DataFrame
    bucket_sensitivity: pd.DataFrame
    weights: dict[str, np.ndarray]


@dataclass(frozen=True)
class ScenarioInputs:
    """Fully transformed inputs for one Phase 2a scenario.

    ``rates`` and ``providers`` are the full Phase 2a margin view.  For ST3 and
    ST4, ``solve_rates``, ``solve_providers`` and ``solve_borrow`` are the
    reduced/relaxed frames used by the optimiser, while ``borrow`` remains the
    original frame used to recompute slack.
    """

    scenario: str
    book: pd.DataFrame
    rates: pd.DataFrame
    providers: pd.DataFrame
    borrow: pd.DataFrame
    solve_rates: pd.DataFrame
    solve_providers: pd.DataFrame
    solve_borrow: pd.DataFrame
    cost_window_start: str
    terminated_pb: object | None = None
    notice_days: int | None = None
    nav_trigger_pct: float | None = None
    top_two: tuple[object, ...] | None = None
    notional_to_move_usd: float | None = None
    positions_moved: int | None = None


@contextmanager
def _unknown_solver_fallback():
    """Retry a HiGHS ``UNKNOWN`` result with CLARABEL.

    HiGHS occasionally returns ``UNKNOWN`` for a numerically infeasible LP
    instead of ``INFEASIBLE``.  That prevents the Phase 1 slack re-solve from
    running.  The retry is solver-only: it does not alter the formulation,
    constraints or objective, and it is active only inside this module's
    optimiser calls.
    """
    original = cp.Problem.solve

    def solve_with_fallback(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except ValueError as exc:
            if "Cannot unpack invalid solution" not in str(exc):
                raise
            return original(self, *args, **{**kwargs, "solver": cp.CLARABEL})

    cp.Problem.solve = solve_with_fallback
    try:
        yield
    finally:
        cp.Problem.solve = original


def _optimise(book, rates, providers, borrow, params):
    with _unknown_solver_fallback():
        return optimise(book, rates, providers, borrow, params)


def annualised_vol(closes: pd.Series, as_of: object) -> float | None:
    """Return Phase 1 annualised vol, or ``None`` with fewer than 60 returns.

    The rule is exactly ``margin.vol_bucket``: last 60 close-to-close log
    returns through ``as_of``, sample standard deviation (``ddof=1``),
    annualised by ``sqrt(252)``.
    """
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
    if values.index.tz is not None:
        values.index = values.index.tz_convert("UTC").tz_localize(None)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("UTC").tz_localize(None)
    values = values.loc[values.index <= cutoff].sort_index()
    returns = np.log(values).diff().dropna().tail(60)
    if len(returns) < 60:
        return None
    return float(returns.std(ddof=1) * np.sqrt(252.0))


def stressed_vol_bucket(
    closes: pd.Series,
    as_of: object,
    multiplier: float,
    cut_low: float = 0.10,
    cut_high: float = 0.20,
) -> str:
    """Return the re-bucketed vol under ``multiplier`` and the given cuts."""
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    if cut_low < 0 or cut_high < cut_low:
        raise ValueError("cutoffs must satisfy 0 <= cut_low <= cut_high")
    vol = annualised_vol(closes, as_of)
    if vol is None:
        return "V3"
    stressed = multiplier * vol
    if stressed < cut_low:
        return "V1"
    if stressed <= cut_high:
        return "V2"
    return "V3"


def _product_buckets(
    prices: pd.DataFrame,
    as_of: object,
    multiplier: float,
    cut_low: float,
    cut_high: float,
) -> dict[object, str]:
    buckets: dict[object, str] = {}
    for product_id, history in prices.groupby("product_id", sort=False):
        closes = history.set_index("date")["close"]
        buckets[product_id] = stressed_vol_bucket(
            closes, as_of, multiplier, cut_low, cut_high
        )
    return buckets


def _book_with_buckets(
    case: Case,
    prices: pd.DataFrame,
    multiplier: float,
    cut_low: float = 0.10,
    cut_high: float = 0.20,
) -> pd.DataFrame:
    book = case.book.copy()
    buckets = _product_buckets(
        prices, case.params["as_of_date"], multiplier, cut_low, cut_high
    )
    book["vol_bucket"] = book["product_id"].map(buckets)
    if book["vol_bucket"].isna().any():
        missing = book.loc[book["vol_bucket"].isna(), "product_id"].unique().tolist()
        raise ValueError(f"price history missing for products: {missing}")
    return book


def _prepare_prices(
    case: Case, prices: pd.DataFrame | None, data_dir: object
) -> pd.DataFrame:
    if prices is None:
        prices = case.raw_tables.get("price_history")
        if prices is None:
            directory = Path(data_dir) if data_dir is not None else Path("data/raw")
            prices = pd.read_csv(directory / "price_history.csv", parse_dates=["date"])
        else:
            prices = prices.copy()
    else:
        prices = prices.copy()
    required = {"product_id", "date", "close"}
    missing = required.difference(prices.columns)
    if missing:
        raise ValueError(f"prices are missing required columns: {', '.join(sorted(missing))}")
    if not pd.api.types.is_datetime64_any_dtype(prices["date"]):
        prices["date"] = pd.to_datetime(prices["date"])
    return prices


def _full_weights(
    weights: np.ndarray, reduced_pbs: list[object], full_pbs: list[object]
) -> np.ndarray:
    values = np.asarray(weights, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(reduced_pbs):
        raise ValueError("weights do not match the reduced provider set")
    if not set(reduced_pbs).issubset(full_pbs):
        raise ValueError("reduced provider set is not a subset of the full set")
    full = np.zeros((values.shape[0], len(full_pbs)), dtype=float)
    for column, pb_id in enumerate(reduced_pbs):
        full[:, full_pbs.index(pb_id)] = values[:, column]
    return full


def _top_two(margin_by_pb_frame: pd.DataFrame, pb_order: list[object]) -> list[object]:
    values = dict(
        zip(
            margin_by_pb_frame["pb_id"],
            margin_by_pb_frame["margin_usd"],
            strict=True,
        )
    )
    order = {pb_id: index for index, pb_id in enumerate(pb_order)}
    return sorted(pb_order, key=lambda pb_id: (-float(values[pb_id]), order[pb_id]))[:2]


def _terminated_pb(
    margin_by_pb_frame: pd.DataFrame, pb_order: list[object]
) -> object:
    values = dict(
        zip(
            margin_by_pb_frame["pb_id"],
            margin_by_pb_frame["margin_usd"],
            strict=True,
        )
    )
    order = {pb_id: index for index, pb_id in enumerate(pb_order)}
    return max(pb_order, key=lambda pb_id: (float(values[pb_id]), -order[pb_id]))


def _relaxed_borrow(borrow: pd.DataFrame, pbs: list[object]) -> pd.DataFrame:
    """Allow every remaining PB for locate shorts; zero availability -> epsilon.

    The epsilon (1e-9 USD) is a numerical enabler, not an economic amount: it
    lets the Phase 1 optimiser build an allowed cell.  The borrow constraint
    still forces the shortfall into ``borrow_slack`` in the slack re-solve, and
    reported slack is recomputed against the original zero availability.
    """
    issuers = list(dict.fromkeys(borrow["issuer_id"].tolist()))
    lookup = borrow.set_index(["pb_id", "issuer_id"])
    rows: list[dict[str, object]] = []
    for pb_id in pbs:
        for issuer_id in issuers:
            key = (pb_id, issuer_id)
            if key in lookup.index:
                source = lookup.loc[key]
                fee = float(source["borrow_fee_bps"])
                available = float(source["borrow_available_usd"])
            else:
                fee = 0.0
                available = 0.0
            rows.append(
                {
                    "pb_id": pb_id,
                    "issuer_id": issuer_id,
                    "borrow_fee_bps": fee,
                    "borrow_available_usd": available if available > 0.0 else 1e-9,
                }
            )
    return pd.DataFrame(
        rows,
        columns=["pb_id", "issuer_id", "borrow_fee_bps", "borrow_available_usd"],
    )


def _slack_amounts(
    book: pd.DataFrame,
    weights: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
    borrow: pd.DataFrame,
) -> dict[str, float]:
    """Recompute the three slack blocks from the returned allocation."""
    pb_ids = providers["pb_id"].tolist()
    notional = book["notional_usd"].to_numpy(dtype=float)
    gross = notional @ weights
    capacity = providers["capacity_usd"].to_numpy(dtype=float)
    capacity_slack = float(np.maximum(0.0, gross - capacity).sum())

    margin = margin_by_pb(book, weights, rates, providers, params)
    limits = providers["counterparty_limit_usd"].to_numpy(dtype=float)
    counterparty_slack = float(
        np.maximum(0.0, margin["margin_usd"].to_numpy(dtype=float) - limits).sum()
    )

    borrow_slack = 0.0
    short_located = (
        book["side"].eq(-1).to_numpy()
        & book["needs_locate"].astype("boolean").fillna(False).to_numpy(dtype=bool)
    )
    if short_located.any() and len(borrow):
        available = borrow.set_index(["pb_id", "issuer_id"])["borrow_available_usd"]
        short_book = book.loc[short_located]
        for column, pb_id in enumerate(pb_ids):
            for issuer_id, group in short_book.groupby("issuer_id", sort=False):
                rows = group.index.to_numpy(dtype=int)
                exposure = float(notional[rows] @ weights[rows, column])
                amount = float(available.get((pb_id, issuer_id), 0.0))
                borrow_slack += max(0.0, exposure - amount)

    return {
        "capacity": 0.0 if capacity_slack <= 1e-6 else capacity_slack,
        "counterparty": 0.0 if counterparty_slack <= 1e-6 else counterparty_slack,
        "borrow": 0.0 if borrow_slack <= 1e-6 else float(borrow_slack),
        "total": (
            0.0
            if capacity_slack + counterparty_slack + borrow_slack <= 1e-6
            else float(capacity_slack + counterparty_slack + borrow_slack)
        ),
    }


def _margin_components(
    book: pd.DataFrame,
    weights: np.ndarray,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    params: object,
) -> pd.DataFrame:
    """Return per-PB margin with offsets and the no-offset position-by-position version."""
    family, issuer = margin_detail(book, weights, rates, providers, params)
    pb_ids = providers["pb_id"].tolist()
    family = family.set_index("pb_id")
    issuer = issuer.set_index("pb_id")
    with_family = family["margin_usd"].groupby(level=0).sum()
    no_offset_family = (family["r"] * family["gross_usd"]).groupby(level=0).sum()
    addon = issuer["addon_usd"].groupby(level=0).sum()
    buffer = float(params["house_buffer"])
    return pd.DataFrame(
        {
            "margin_with_offsets_usd": (buffer * (with_family + addon)).reindex(pb_ids).fillna(0.0),
            "margin_without_offsets_usd": (buffer * (no_offset_family + addon)).reindex(pb_ids).fillna(0.0),
        },
        index=pd.Index(pb_ids, name="pb_id"),
    )


def _evaluate(
    case: Case,
    book: pd.DataFrame,
    result: object,
    scenario: str,
    solve_pbs: list[object],
    margin_rates: pd.DataFrame,
) -> dict[str, object]:
    status = str(result.status)
    if status not in {"optimal", "infeasible"}:
        raise RuntimeError(f"{scenario} returned unsupported status {status!r}")
    full_pbs = case.providers["pb_id"].tolist()
    weights = _full_weights(np.asarray(result.w, dtype=float), solve_pbs, full_pbs)
    margin = margin_by_pb(book, weights, margin_rates, case.providers, case.params)
    total_margin = float(margin["margin_usd"].sum())
    slacks = _slack_amounts(
        book, weights, margin_rates, case.providers, case.params, case.borrow
    )
    if status == "optimal":
        if max(slacks.values()) > 1e-6:
            raise RuntimeError(
                f"{scenario} reported optimal but recomputed slack is "
                f"{max(slacks.values()):.6g} USD"
            )
        slacks = {"capacity": 0.0, "counterparty": 0.0, "borrow": 0.0, "total": 0.0}
        financing = float(result.financing_usd)
        scale = (
            float(case.params["liquidity_premium_bps"])
            * 1e-4
            * float(case.params["horizon_days"])
            / 360.0
        )
        margin_funding = total_margin * scale
    else:
        if float(slacks["total"]) <= 1e-6:
            raise RuntimeError(
                f"{scenario} reported infeasible but recomputed slack is "
                f"{float(slacks['total']):.6g} USD"
            )
        financing = float("nan")
        margin_funding = float("nan")
    return {
        "result": result,
        "weights": weights,
        "margin": margin,
        "total_margin": total_margin,
        "financing": financing,
        "margin_funding": margin_funding,
        "slacks": slacks,
        "status": status,
    }


def _moves_table(
    book: pd.DataFrame,
    st0_weights: np.ndarray,
    weights_by_scenario: dict[str, np.ndarray],
    pb_ids: list[object],
) -> pd.DataFrame:
    notional = book["notional_usd"].to_numpy(dtype=float)
    pos_ids = book["pos_id"].tolist()
    records: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        scenario_weights = weights_by_scenario[scenario]
        for row, pos_id in enumerate(pos_ids):
            difference = scenario_weights[row] - st0_weights[row]
            difference[np.abs(difference) <= 1e-9] = 0.0
            outflow = notional[row] * np.maximum(0.0, -difference)
            inflow = notional[row] * np.maximum(0.0, difference)
            for from_column, from_pb in enumerate(pb_ids):
                for to_column, to_pb in enumerate(pb_ids):
                    if from_column == to_column:
                        continue
                    moved = min(outflow[from_column], inflow[to_column])
                    if moved >= 1e-6:
                        records.append(
                            {
                                "scenario": scenario,
                                "pos_id": pos_id,
                                "from_pb": from_pb,
                                "to_pb": to_pb,
                                "notional_moved_usd": float(moved),
                            }
                        )
                        outflow[from_column] -= moved
                        inflow[to_column] -= moved
    moves = pd.DataFrame(records, columns=list(MOVES_COLUMNS))
    if len(moves):
        scenario_order = {scenario: index for index, scenario in enumerate(SCENARIOS)}
        moves["_scenario_order"] = moves["scenario"].map(scenario_order)
        moves = moves.sort_values(
            ["_scenario_order", "pos_id", "from_pb", "to_pb"], kind="mergesort"
        ).drop(columns="_scenario_order")
    return moves.reset_index(drop=True)


def _st3_netting_table(
    case: Case,
    st0_weights: np.ndarray,
    st3_weights: np.ndarray,
    st3_total_margin: float,
    terminated_pb: object,
) -> pd.DataFrame:
    pb_ids = case.providers["pb_id"].tolist()
    st3 = _margin_components(
        case.book, st3_weights, case.rates, case.providers, case.params
    )
    st0 = _margin_components(
        case.book, st0_weights, case.rates, case.providers, case.params
    )
    rows: list[dict[str, object]] = []
    for pb_id in pb_ids:
        with_offsets = float(st3.loc[pb_id, "margin_with_offsets_usd"])
        without_offsets = float(st3.loc[pb_id, "margin_without_offsets_usd"])
        st0_with = float(st0.loc[pb_id, "margin_with_offsets_usd"])
        st0_without = float(st0.loc[pb_id, "margin_without_offsets_usd"])
        benefit = without_offsets - with_offsets
        st0_benefit = st0_without - st0_with
        netting_change = st0_benefit - benefit
        reallocation = without_offsets - st0_without
        delta = with_offsets - st0_with
        rows.append(
            {
                "scenario": "ST3",
                "pb_id": pb_id,
                "role": "terminated" if pb_id == terminated_pb else "receiving",
                "margin_with_offsets_usd": with_offsets,
                "margin_without_offsets_usd": without_offsets,
                "netting_benefit_usd": benefit,
                "st0_margin_with_offsets_usd": st0_with,
                "st0_margin_without_offsets_usd": st0_without,
                "st0_netting_benefit_usd": st0_benefit,
                "netting_change_usd": netting_change,
                "reallocation_effect_usd": reallocation,
                "delta_margin_vs_st0_usd": delta,
                "identity_residual_usd": delta - reallocation - netting_change,
            }
        )
    total = {
        "scenario": "ST3",
        "pb_id": "TOTAL",
        "role": "total",
    }
    for column in NETTING_COLUMNS[3:]:
        total[column] = float(sum(row[column] for row in rows))
    rows.append(total)
    table = pd.DataFrame(rows, columns=list(NETTING_COLUMNS))
    if abs(float(table.loc[table["pb_id"].eq("TOTAL"), "margin_with_offsets_usd"].iloc[0]) - st3_total_margin) > 1e-6:
        raise RuntimeError("ST3 netting table does not reconcile to total margin")
    return table


def _summary_table(
    case: Case,
    evaluations: dict[str, dict[str, object]],
    terminated_pb: object,
    notice_days: int,
    nav_trigger_pct: float,
    notional_to_move: float,
) -> pd.DataFrame:
    as_of = pd.Timestamp(case.params["as_of_date"])
    termination_date = (as_of + pd.Timedelta(days=int(notice_days))).date().isoformat()
    st0 = evaluations["ST0"]
    st0_margin = float(st0["total_margin"])
    st0_financing = float(st0["financing"])
    st0_margin_funding = float(st0["margin_funding"])
    rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        evaluation = evaluations[scenario]
        total_margin = float(evaluation["total_margin"])
        financing = float(evaluation["financing"])
        margin_funding = float(evaluation["margin_funding"])
        slacks = evaluation["slacks"]
        delta_margin = total_margin - st0_margin
        delta_financing = (
            financing - st0_financing
            if np.isfinite(financing) and np.isfinite(st0_financing)
            else float("nan")
        )
        delta_margin_funding = (
            margin_funding - st0_margin_funding
            if np.isfinite(margin_funding) and np.isfinite(st0_margin_funding)
            else float("nan")
        )
        rows.append(
            {
                "scenario": scenario,
                "cost_window_start": termination_date if scenario in TERMINATION_SCENARIOS else as_of.date().isoformat(),
                "total_margin_usd": total_margin,
                "delta_margin_usd": delta_margin,
                "financing_cost_usd": financing,
                "delta_financing_cost_usd": delta_financing,
                "margin_funding_cost_usd": margin_funding,
                "delta_margin_funding_cost_usd": delta_margin_funding,
                "status": str(evaluation["status"]),
                "slack_capacity_usd": float(slacks["capacity"]),
                "slack_counterparty_usd": float(slacks["counterparty"]),
                "slack_borrow_usd": float(slacks["borrow"]),
                "total_slack_usd": float(slacks["total"]),
                "additional_funding_requirement_usd": float(delta_margin + slacks["total"]),
                "terminated_pb": terminated_pb if scenario in TERMINATION_SCENARIOS else np.nan,
                "notice_days": int(notice_days) if scenario in TERMINATION_SCENARIOS else np.nan,
                "nav_trigger_pct": float(nav_trigger_pct) if scenario in TERMINATION_SCENARIOS else np.nan,
                "notional_to_move_usd": float(notional_to_move) if scenario in TERMINATION_SCENARIOS else np.nan,
            }
        )
    summary = pd.DataFrame(rows, columns=list(SUMMARY_COLUMNS))
    summary["notice_days"] = summary["notice_days"].astype("Int64")
    return summary


def _margin_by_pb_table(
    case: Case,
    evaluations: dict[str, dict[str, object]],
    terminated_pb: object,
) -> pd.DataFrame:
    pb_ids = case.providers["pb_id"].tolist()
    notional = case.book["notional_usd"].to_numpy(dtype=float)
    capacities = dict(
        zip(
            case.providers["pb_id"],
            case.providers["capacity_usd"].astype(float),
            strict=True,
        )
    )
    rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        evaluation = evaluations[scenario]
        margin = evaluation["margin"]
        weights = evaluation["weights"]
        gross = notional @ weights
        for column, pb_id in enumerate(pb_ids):
            capacity = 0.0 if scenario in TERMINATION_SCENARIOS and pb_id == terminated_pb else float(capacities[pb_id])
            if capacity == 0.0:
                utilisation = 0.0 if gross[column] <= 1e-9 else float("nan")
            else:
                utilisation = 100.0 * float(gross[column]) / capacity
            rows.append(
                {
                    "scenario": scenario,
                    "pb_id": pb_id,
                    "margin_usd": float(margin.loc[margin["pb_id"].eq(pb_id), "margin_usd"].iloc[0]),
                    "gross_usd": float(gross[column]),
                    "capacity_usd": capacity,
                    "utilisation_pct": utilisation,
                }
            )
    return pd.DataFrame(rows, columns=list(MARGIN_BY_PB_COLUMNS))


def _bucket_sensitivity(case: Case, prices: pd.DataFrame) -> pd.DataFrame:
    book = _book_with_buckets(case, prices, 2.0, 0.12, 0.24)
    result = _optimise(book, case.rates, case.providers, case.borrow, case.params)
    full_pbs = case.providers["pb_id"].tolist()
    weights = _full_weights(np.asarray(result.w, dtype=float), full_pbs, full_pbs)
    total_margin = float(
        margin_by_pb(book, weights, case.rates, case.providers, case.params)[
            "margin_usd"
        ].sum()
    )
    return pd.DataFrame(
        [
            {
                "scenario": "ST1a_cuts_0.12_0.24",
                "cut_low": 0.12,
                "cut_high": 0.24,
                "total_margin_usd": total_margin,
                "delta_margin_vs_st0_usd": float("nan"),
                "status": str(result.status),
            }
        ],
        columns=list(SENSITIVITY_COLUMNS),
    )


def _st0_facts(
    case: Case, st0: StressResult | dict[str, object] | None
) -> tuple[np.ndarray, pd.DataFrame]:
    """Return ST0 weights and per-PB margin, reusing a supplied result if possible."""
    if st0 is None:
        result = _optimise(
            case.book, case.rates, case.providers, case.borrow, case.params
        )
        if str(result.status) != "optimal":
            raise RuntimeError(f"ST0 is not optimal: {result.status}")
        weights = np.asarray(result.w, dtype=float)
        margin = margin_by_pb(
            case.book, weights, case.rates, case.providers, case.params
        )
        return weights, margin
    if isinstance(st0, StressResult):
        weights = np.asarray(st0.weights["ST0"], dtype=float)
        margin = (
            st0.margin_by_pb[st0.margin_by_pb["scenario"].eq("ST0")][
                ["pb_id", "margin_usd"]
            ]
            .reset_index(drop=True)
        )
        return weights, margin
    if isinstance(st0, dict) and {"weights", "margin"}.issubset(st0):
        return np.asarray(st0["weights"], dtype=float), st0["margin"].copy()
    raise TypeError("st0 must be None, a StressResult, or a dict with weights and margin")


def scenario_inputs(
    case: Case,
    scenario: str,
    prices: pd.DataFrame | None = None,
    data_dir: object = None,
    st0: StressResult | dict[str, object] | None = None,
) -> ScenarioInputs:
    """Return the fixed transformed inputs for ``scenario``.

    ST0, ST1a, ST1b, ST2a and ST2b use the full provider set.  ST3 and ST4
    remove the terminated PB from ``solve_*`` while retaining the full
    ``rates``/``providers`` frames for margin and the original ``borrow`` for
    slack reconciliation.  Passing the ST0 result avoids re-solving it.
    """
    if scenario not in SCENARIOS:
        raise ValueError(
            f"unknown scenario {scenario!r}; expected one of {', '.join(SCENARIOS)}"
        )
    full_pbs = case.providers["pb_id"].tolist()
    as_of = pd.Timestamp(case.params["as_of_date"])
    st0_weights, st0_margin = _st0_facts(case, st0)
    top_two = tuple(_top_two(st0_margin, full_pbs))
    terminated_pb = _terminated_pb(st0_margin, full_pbs)
    provider_lookup = case.providers.set_index("pb_id")
    notice_days = int(provider_lookup.loc[terminated_pb, "notice_days"])
    nav_trigger_pct = float(provider_lookup.loc[terminated_pb, "nav_trigger_pct"])

    book = case.book.copy()
    rates = case.rates.copy()
    providers = case.providers.copy()
    borrow = case.borrow.copy()
    solve_rates = rates
    solve_providers = providers
    solve_borrow = borrow
    cost_window_start = as_of.date().isoformat()
    terminated = None
    notice = None
    nav = None
    top = None
    notional_to_move = None
    positions_moved = None

    if scenario in {"ST1a", "ST1b"}:
        multiplier = 2.0 if scenario == "ST1a" else 1.5
        book = _book_with_buckets(
            case, _prepare_prices(case, prices, data_dir), multiplier
        )
    elif scenario == "ST2a":
        rates["base_rate"] = rates["base_rate"].astype(float) * 1.5
    elif scenario == "ST2b":
        top = top_two
        shocked = rates["pb_id"].isin(top_two)
        rates.loc[shocked, "base_rate"] = (
            rates.loc[shocked, "base_rate"].astype(float) * 1.5
        )
    elif scenario in TERMINATION_SCENARIOS:
        terminated = terminated_pb
        notice = notice_days
        nav = nav_trigger_pct
        cost_window_start = (
            as_of + pd.Timedelta(days=notice_days)
        ).date().isoformat()
        if scenario == "ST4":
            top = top_two
            book = _book_with_buckets(
                case, _prepare_prices(case, prices, data_dir), 2.0
            )
            shocked = rates["pb_id"].isin(top_two)
            rates.loc[shocked, "base_rate"] = (
                rates.loc[shocked, "base_rate"].astype(float) * 1.5
            )
        if scenario in TERMINATION_SCENARIOS:
            column = full_pbs.index(terminated_pb)
            notional_to_move = float(
                case.book["notional_usd"].to_numpy(dtype=float)
                @ st0_weights[:, column]
            )
            positions_moved = int((st0_weights[:, column] > 1e-9).sum())
        remaining_pbs = [pb_id for pb_id in full_pbs if pb_id != terminated_pb]
        solve_providers = (
            providers[providers["pb_id"].isin(remaining_pbs)]
            .reset_index(drop=True)
        )
        solve_rates = (
            rates[rates["pb_id"].isin(remaining_pbs)].reset_index(drop=True)
        )
        solve_borrow = _relaxed_borrow(borrow, remaining_pbs)

    return ScenarioInputs(
        scenario=scenario,
        book=book,
        rates=rates,
        providers=providers,
        borrow=borrow,
        solve_rates=solve_rates,
        solve_providers=solve_providers,
        solve_borrow=solve_borrow,
        cost_window_start=cost_window_start,
        terminated_pb=terminated,
        notice_days=notice,
        nav_trigger_pct=nav,
        top_two=top,
        notional_to_move_usd=notional_to_move,
        positions_moved=positions_moved,
    )


def run_scenarios(
    case: Case,
    prices: pd.DataFrame | None = None,
    data_dir: object = None,
) -> StressResult:
    """Run ST0–ST4 and return the pre-registered tables.

    ``prices`` is used only for ST1a/ST1b.  If omitted, it is taken from
    ``case.raw_tables["price_history"]`` or ``data_dir/price_history.csv``
    (default ``data/raw``).  No input frame is mutated.
    """
    prices = _prepare_prices(case, prices, data_dir)
    full_pbs = case.providers["pb_id"].tolist()

    st0_result = _optimise(case.book, case.rates, case.providers, case.borrow, case.params)
    if str(st0_result.status) != "optimal":
        raise RuntimeError(f"ST0 is not optimal: {st0_result.status}")
    st0 = _evaluate(
        case,
        case.book,
        st0_result,
        "ST0",
        full_pbs,
        case.rates,
    )
    inputs = {
        scenario: scenario_inputs(case, scenario, prices=prices, st0=st0)
        for scenario in SCENARIOS
    }
    terminated_pb = inputs["ST3"].terminated_pb
    notice_days = inputs["ST3"].notice_days
    nav_trigger_pct = inputs["ST3"].nav_trigger_pct
    notional_to_move = inputs["ST3"].notional_to_move_usd
    if terminated_pb is None or notice_days is None or nav_trigger_pct is None:
        raise RuntimeError("ST3 inputs missing termination facts")

    evaluations: dict[str, dict[str, object]] = {"ST0": st0}
    for scenario in SCENARIOS[1:]:
        transformed = inputs[scenario]
        result = _optimise(
            transformed.book,
            transformed.solve_rates,
            transformed.solve_providers,
            transformed.solve_borrow,
            case.params,
        )
        evaluations[scenario] = _evaluate(
            case,
            transformed.book,
            result,
            scenario,
            transformed.solve_providers["pb_id"].tolist(),
            transformed.rates,
        )
    weights_by_scenario = {
        scenario: evaluations[scenario]["weights"] for scenario in SCENARIOS
    }

    summary = _summary_table(
        case,
        evaluations,
        terminated_pb,
        notice_days,
        nav_trigger_pct,
        notional_to_move,
    )
    margin_table = _margin_by_pb_table(case, evaluations, terminated_pb)
    moves = _moves_table(case.book, st0["weights"], weights_by_scenario, full_pbs)
    st3_netting = _st3_netting_table(
        case,
        st0["weights"],
        evaluations["ST3"]["weights"],
        float(evaluations["ST3"]["total_margin"]),
        terminated_pb,
    )
    sensitivity = _bucket_sensitivity(case, prices)
    sensitivity.loc[0, "delta_margin_vs_st0_usd"] = float(
        sensitivity.loc[0, "total_margin_usd"] - st0["total_margin"]
    )
    return StressResult(
        summary=summary,
        margin_by_pb=margin_table,
        moves=moves,
        st3_netting=st3_netting,
        bucket_sensitivity=sensitivity,
        weights=weights_by_scenario,
    )


def _rounded_for_csv(frame: pd.DataFrame, decimals: int = 7) -> pd.DataFrame:
    """Round stress-result floats for CSV display without changing Phase 1 output."""
    rounded = frame.copy()
    float_columns = rounded.select_dtypes(include=["floating"]).columns
    if len(float_columns):
        rounded[float_columns] = rounded[float_columns].round(decimals)
    return rounded


def _format_csv_float(value: float) -> str:
    if pd.isna(value):
        return ""
    return repr(round(float(value), 7))


def _write_stress_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write a stress CSV with compact floats; io.write_csv is deliberately untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _rounded_for_csv(frame).to_csv(
        path,
        index=False,
        float_format=_format_csv_float,
        lineterminator="\n",
        encoding="utf-8",
    )


def write_outputs(result: StressResult, out_dir: object) -> list[Path]:
    """Write the Phase 2a CSVs and return their paths."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    frames = {
        "stress_summary": result.summary,
        "stress_margin_by_pb": result.margin_by_pb,
        "stress_moves": result.moves,
        "stress_st3_netting": result.st3_netting,
        "stress_bucket_sensitivity": result.bucket_sensitivity,
    }
    paths: list[Path] = []
    for name, frame in frames.items():
        path = directory / f"{name}.csv"
        _write_stress_csv(frame, path)
        paths.append(path)
    return paths
