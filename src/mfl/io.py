"""Input loading and deterministic CSV output for the MFL pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .margin import validate_rates, vol_bucket


@dataclass(frozen=True)
class Case:
    book: pd.DataFrame
    rates: pd.DataFrame
    providers: pd.DataFrame
    borrow: pd.DataFrame
    pms: pd.DataFrame
    params: dict[str, object]
    raw_tables: dict[str, pd.DataFrame]


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.upper().eq("TRUE")


def load_case(data_dir: Path) -> Case:
    data_dir = Path(data_dir)
    params_frame = pd.read_csv(data_dir / "params.csv", dtype={"name": str, "value": str})
    raw = dict(zip(params_frame["name"], params_frame["value"], strict=True))
    params: dict[str, object] = {
        key: (value if key == "as_of_date" else int(float(value)) if key == "seed" else float(value))
        for key, value in raw.items()
    }
    params["vol_multipliers"] = {
        "V1": params["vol_mult_v1"], "V2": params["vol_mult_v2"], "V3": params["vol_mult_v3"]
    }
    rates = pd.read_csv(data_dir / "pb_rates.csv")
    validate_rates(rates)
    providers = pd.read_csv(data_dir / "providers.csv")
    borrow = pd.read_csv(data_dir / "pb_borrow.csv")
    pms = pd.read_csv(data_dir / "pms.csv")
    if not (rates["phi"] == float(params["phi"])).all():
        raise ValueError("params.csv phi does not match pb_rates.csv")
    if not (providers["conc_threshold"] == float(params["conc_threshold"])).all():
        raise ValueError("params.csv conc_threshold does not match providers.csv")
    if not (providers["conc_rate"] == float(params["conc_rate"])).all():
        raise ValueError("params.csv conc_rate does not match providers.csv")

    positions = pd.read_csv(data_dir / "positions.csv")
    products = pd.read_csv(data_dir / "products.csv")
    issuers = pd.read_csv(data_dir / "issuers.csv")
    prices = pd.read_csv(data_dir / "price_history.csv", parse_dates=["date"])
    product_fields = products[["product_id", "product_type", "issuer_id", "needs_locate"]].copy()
    product_fields["needs_locate"] = _bool(product_fields["needs_locate"])
    issuer_fields = issuers[["issuer_id", "conc_eligible"]].copy()
    issuer_fields["conc_eligible"] = _bool(issuer_fields["conc_eligible"])
    book = positions.merge(product_fields, on="product_id", how="left", validate="many_to_one")
    book = book.merge(issuer_fields, on="issuer_id", how="left", validate="many_to_one")
    book["conc_eligible"] = book["conc_eligible"].astype("boolean").fillna(False).astype(bool)
    buckets = {}
    for product_id, history in prices.groupby("product_id", sort=False):
        buckets[product_id] = vol_bucket(
            history.set_index("date")["close"], params["as_of_date"],
            float(params["vol_cut_low"]), float(params["vol_cut_high"]),
        )
    book["vol_bucket"] = book["product_id"].map(buckets)
    if book["vol_bucket"].isna().any():
        missing = book.loc[book["vol_bucket"].isna(), "product_id"].unique().tolist()
        raise ValueError(f"price history missing for products: {missing}")
    return Case(book, rates, providers, borrow, pms, params,
                {"positions": positions, "products": products, "issuers": issuers})


_SORT_KEYS = {
    "positions_alloc": ["pos_id", "pb_id"], "margin_by_pb": ["pb_id"],
    "margin_family": ["pb_id", "product_id", "liquidity_tier", "vol_bucket"],
    "margin_issuer": ["pb_id", "issuer_id"], "duals_capacity": ["pb_id"],
    "duals_counterparty": ["pb_id"], "duals_borrow": ["pb_id", "issuer_id"],
    "attribution": ["pm_id"], "resolve": ["pm_id"], "all_in": ["pm_id"],
    "euler": ["pm_id"], "kinks": ["kind", "key", "pb_id"],
    "sensitivity_summary": ["scenario"], "sensitivity_pb": ["scenario", "pb_id"],
    "sensitivity_pm": ["scenario", "pm_id"], "run_summary": [],
}


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _SORT_KEYS.get(path.stem, [])
    out = df.sort_values(keys, kind="mergesort", na_position="last") if keys and len(df) else df
    out.to_csv(path, index=False, float_format="%.17g", lineterminator="\n", encoding="utf-8")
