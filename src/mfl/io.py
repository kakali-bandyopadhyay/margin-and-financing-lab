"""Input loading and deterministic CSV output for the MFL pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import math
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
    values = series.astype(str).str.strip().str.upper()
    invalid = ~values.isin({"TRUE", "FALSE"})
    if invalid.any():
        raise ValueError(f"invalid boolean values: {series.loc[invalid].unique().tolist()}")
    return values.eq("TRUE")


_PARAMETER_NAMES = {
    "as_of_date", "horizon_days", "liquidity_premium_bps", "house_buffer",
    "pass_through_bps", "phi", "conc_threshold", "conc_rate", "vol_cut_low",
    "vol_cut_high", "vol_mult_v1", "vol_mult_v2", "vol_mult_v3", "seed",
}
_RAW_TABLES = (
    "pms.csv", "issuers.csv", "products.csv", "providers.csv", "price_history.csv",
    "positions.csv", "pb_rates.csv", "pb_borrow.csv",
)
_PRODUCT_ASSET_CLASS = {
    "cash_equity": "equity", "equity_swap": "equity", "govt_bond": "rates",
    "irs_proxy_future": "rates", "fx_forward": "fx", "commodity_future": "commodity",
    "cds_proxy": "credit",
}
_ISSUER_PRODUCT_TYPES = {"cash_equity", "equity_swap", "govt_bond", "cds_proxy"}
_LOCATE_PRODUCT_TYPES = {"cash_equity", "equity_swap", "govt_bond"}


def _validate_provenance(data_dir: Path, parameter_names: set[str]) -> None:
    source_file = data_dir.parent / "SOURCES.md"
    if not source_file.is_file():
        raise ValueError(f"provenance register missing: {source_file}")
    lines = source_file.read_text(encoding="utf-8").splitlines()

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    for filename in _RAW_TABLES:
        matches = [cells(line) for line in lines if line.lstrip().startswith("|") and cells(line)[0] == filename]
        if not matches or len(matches[0]) < 7 or not matches[0][6]:
            raise ValueError(f"provenance tag missing for {filename} in SOURCES.md")
        tag = matches[0][6].lower()
        if not tag.startswith(("source", "assumed", "to-be-calibrated")):
            raise ValueError(f"invalid provenance tag for {filename} in SOURCES.md: {matches[0][6]}")

    try:
        section_start = next(i for i, line in enumerate(lines) if line.startswith("## 3. Model parameters"))
    except StopIteration as exc:
        raise ValueError("parameter provenance section missing from SOURCES.md") from exc
    section_end = next(
        (i for i in range(section_start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    parameter_tags: dict[str, str] = {}
    for line in lines[section_start:section_end]:
        if not line.lstrip().startswith("|"):
            continue
        row = cells(line)
        if len(row) >= 3 and row[0].lower() not in {"name", "---"} and set(row[0]) != {"-"}:
            parameter_tags[row[0].strip().lower()] = row[2].strip()

    aliases = {
        "vol_cut_low": "vol cut-offs", "vol_cut_high": "vol cut-offs",
        "vol_mult_v1": "vol multipliers", "vol_mult_v2": "vol multipliers",
        "vol_mult_v3": "vol multipliers",
    }
    for name in parameter_names:
        source_name = aliases.get(name, name).lower()
        tag = parameter_tags.get(source_name, "")
        tag_lower = tag.lower()
        if not tag or (
            not tag_lower.startswith(("source", "assumed", "to-be-calibrated"))
            and not (name == "seed" and tag_lower in {"-", "–", "—"})
        ):
            raise ValueError(f"provenance tag missing for parameter {name} in SOURCES.md")


def _validate_case_tables(
    positions: pd.DataFrame,
    products: pd.DataFrame,
    issuers: pd.DataFrame,
    pms: pd.DataFrame,
    rates: pd.DataFrame,
    providers: pd.DataFrame,
    borrow: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    def require_columns(frame: pd.DataFrame, name: str, required: set[str]) -> None:
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name}.csv missing required columns: {', '.join(sorted(missing))}")

    require_columns(positions, "positions", {"pos_id", "pm_id", "product_id", "side", "notional_usd", "liquidity_tier"})
    require_columns(products, "products", {"product_id", "asset_class", "product_type", "issuer_id", "needs_locate"})
    require_columns(issuers, "issuers", {"issuer_id", "asset_class", "conc_eligible"})
    require_columns(pms, "pms", {"pm_id"})
    require_columns(rates, "pb_rates", {"pb_id", "product_id", "liquidity_tier", "base_rate", "phi"})
    require_columns(providers, "providers", {"pb_id", "conc_threshold", "conc_rate"})
    require_columns(borrow, "pb_borrow", {"pb_id", "issuer_id"})

    for frame, filename, key in (
        (positions, "positions", "pos_id"), (products, "products", "product_id"),
        (issuers, "issuers", "issuer_id"), (pms, "pms", "pm_id"), (providers, "providers", "pb_id"),
    ):
        if frame[key].isna().any() or frame[key].duplicated().any():
            raise ValueError(f"{filename}.csv must have unique, non-missing {key} values")

    if rates.duplicated(["pb_id", "product_id", "liquidity_tier"]).any():
        raise ValueError("pb_rates.csv has duplicate (pb_id, product_id, liquidity_tier) keys")
    if borrow.duplicated(["pb_id", "issuer_id"]).any():
        raise ValueError("pb_borrow.csv has duplicate (pb_id, issuer_id) keys")

    theta = pd.to_numeric(providers["conc_threshold"], errors="coerce")
    concentration_rate = pd.to_numeric(providers["conc_rate"], errors="coerce")
    if not theta.map(lambda value: pd.notna(value) and math.isfinite(float(value))).all() or ((theta <= 0) | (theta >= 1)).any():
        raise ValueError("providers.csv conc_threshold must satisfy 0 < conc_threshold < 1")
    if not concentration_rate.map(lambda value: pd.notna(value) and math.isfinite(float(value))).all() or (concentration_rate < 0).any():
        raise ValueError("providers.csv conc_rate must be finite and nonnegative")

    product_fields = products.copy()
    product_fields["needs_locate"] = _bool(product_fields["needs_locate"])
    unknown_types = set(product_fields["product_type"].dropna()) - set(_PRODUCT_ASSET_CLASS)
    if unknown_types:
        raise ValueError(f"products.csv has unsupported product_type values: {sorted(unknown_types)}")
    expected_asset_class = product_fields["product_type"].map(_PRODUCT_ASSET_CLASS)
    wrong_class = product_fields["asset_class"].ne(expected_asset_class)
    if wrong_class.any():
        ids = product_fields.loc[wrong_class, "product_id"].tolist()
        raise ValueError(f"products.csv asset_class does not match product_type for: {ids}")
    requires_issuer = product_fields["product_type"].isin(_ISSUER_PRODUCT_TYPES)
    missing_issuer = requires_issuer & product_fields["issuer_id"].isna()
    extra_issuer = ~requires_issuer & product_fields["issuer_id"].notna()
    if (missing_issuer | extra_issuer).any():
        ids = product_fields.loc[missing_issuer | extra_issuer, "product_id"].tolist()
        raise ValueError(f"products.csv issuer_id does not match product_type requirements for: {ids}")
    invalid_locate = product_fields["needs_locate"] & ~product_fields["product_type"].isin(_LOCATE_PRODUCT_TYPES)
    if invalid_locate.any():
        ids = product_fields.loc[invalid_locate, "product_id"].tolist()
        raise ValueError(f"products.csv needs_locate is not allowed for product types: {ids}")

    issuer_fields = issuers.copy()
    issuer_fields["conc_eligible"] = _bool(issuer_fields["conc_eligible"])
    allowed_concentration_classes = {"equity", "credit"}
    invalid_eligible = issuer_fields["conc_eligible"] & ~issuer_fields["asset_class"].isin(allowed_concentration_classes)
    if invalid_eligible.any():
        ids = issuer_fields.loc[invalid_eligible, "issuer_id"].tolist()
        raise ValueError(f"issuers.csv conc_eligible is only allowed for corporate equity or credit: {ids}")
    unknown_issuers = set(product_fields["issuer_id"].dropna()) - set(issuer_fields["issuer_id"])
    if unknown_issuers:
        raise ValueError(f"products.csv references unknown issuer_id values: {sorted(unknown_issuers)}")

    unknown_pms = set(positions["pm_id"].dropna()) - set(pms["pm_id"])
    unknown_products = set(positions["product_id"].dropna()) - set(product_fields["product_id"])
    if unknown_pms:
        raise ValueError(f"positions.csv references unknown pm_id values: {sorted(unknown_pms)}")
    if unknown_products:
        raise ValueError(f"positions.csv references unknown product_id values: {sorted(unknown_products)}")
    side = pd.to_numeric(positions["side"], errors="coerce")
    notional = pd.to_numeric(positions["notional_usd"], errors="coerce")
    if side.isna().any() or not side.isin({-1, 1}).all():
        raise ValueError("positions.csv side must be either -1 or +1")
    if not notional.map(lambda value: pd.notna(value) and math.isfinite(float(value))).all() or (notional <= 0).any():
        raise ValueError("positions.csv notional_usd must be finite and positive")
    if not positions["liquidity_tier"].isin({"L1", "L2", "L3"}).all():
        raise ValueError("positions.csv liquidity_tier must be L1, L2 or L3")

    pb_ids = set(providers["pb_id"])
    unknown_rate_pbs = set(rates["pb_id"]) - pb_ids
    if unknown_rate_pbs:
        raise ValueError(f"pb_rates.csv references unknown PBs: {sorted(unknown_rate_pbs)}")
    held_keys = set(zip(positions["product_id"], positions["liquidity_tier"], strict=True))
    rates_by_pb = {
        pb_id: set(zip(group["product_id"], group["liquidity_tier"], strict=True))
        for pb_id, group in rates.groupby("pb_id", sort=False)
    }
    missing_rates = [
        (pb_id, product_id, tier)
        for pb_id in providers["pb_id"]
        for product_id, tier in held_keys
        if (product_id, tier) not in rates_by_pb.get(pb_id, set())
    ]
    if missing_rates:
        raise ValueError(f"pb_rates.csv missing rates for held positions: {missing_rates[:5]}")
    unknown_borrow_pbs = set(borrow["pb_id"]) - pb_ids
    unknown_borrow_issuers = set(borrow["issuer_id"]) - set(issuer_fields["issuer_id"])
    if unknown_borrow_pbs or unknown_borrow_issuers:
        raise ValueError("pb_borrow.csv references unknown PB or issuer keys")
    return (
        product_fields[["product_id", "product_type", "issuer_id", "needs_locate"]],
        issuer_fields[["issuer_id", "conc_eligible"]],
    )


def load_case(data_dir: Path) -> Case:
    data_dir = Path(data_dir)
    params_frame = pd.read_csv(data_dir / "params.csv", dtype={"name": str, "value": str})
    if params_frame["name"].isna().any() or params_frame["name"].duplicated().any():
        raise ValueError("params.csv must have unique, non-missing parameter names")
    parameter_names = set(params_frame["name"])
    missing_params = _PARAMETER_NAMES - parameter_names
    extra_params = parameter_names - _PARAMETER_NAMES
    if missing_params or extra_params:
        raise ValueError(
            f"params.csv parameter names differ from the required set; missing={sorted(missing_params)}, "
            f"extra={sorted(extra_params)}"
        )
    _validate_provenance(data_dir, parameter_names)
    raw = dict(zip(params_frame["name"], params_frame["value"], strict=True))
    try:
        params: dict[str, object] = {
            key: (value if key == "as_of_date" else int(float(value)) if key == "seed" else float(value))
            for key, value in raw.items()
        }
        pd.Timestamp(params["as_of_date"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("params.csv contains an invalid date or numeric value") from exc
    numeric_params = [name for name in _PARAMETER_NAMES if name != "as_of_date"]
    if any(not math.isfinite(float(params[name])) for name in numeric_params):
        raise ValueError("params.csv numeric parameters must be finite")
    if float(params["phi"]) < 0 or float(params["phi"]) >= 1:
        raise ValueError("params.csv phi must satisfy 0 <= phi < 1")
    if float(params["conc_threshold"]) <= 0 or float(params["conc_threshold"]) >= 1:
        raise ValueError("params.csv conc_threshold must satisfy 0 < conc_threshold < 1")
    if float(params["conc_rate"]) < 0:
        raise ValueError("params.csv conc_rate must be nonnegative")
    if float(params["liquidity_premium_bps"]) < 0:
        raise ValueError("params.csv liquidity_premium_bps must be nonnegative")
    if float(params["house_buffer"]) <= 0 or float(params["horizon_days"]) <= 0:
        raise ValueError("params.csv house_buffer and horizon_days must be positive")
    if float(params["pass_through_bps"]) < 0:
        raise ValueError("params.csv pass_through_bps must be nonnegative")
    if float(params["vol_cut_low"]) < 0 or float(params["vol_cut_high"]) <= float(params["vol_cut_low"]):
        raise ValueError("params.csv volatility cut-offs must satisfy 0 <= low < high")
    if any(float(params[f"vol_mult_{bucket}"]) <= 0 for bucket in ("v1", "v2", "v3")):
        raise ValueError("params.csv volatility multipliers must be positive")
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
    product_fields, issuer_fields = _validate_case_tables(
        positions, products, issuers, pms, rates, providers, borrow
    )
    prices = pd.read_csv(data_dir / "price_history.csv", parse_dates=["date"])
    held_products = set(positions["product_id"])
    price_products = set(prices["product_id"].dropna())
    missing_price = sorted(held_products - price_products)
    if missing_price:
        raise ValueError(f"price history missing for products: {missing_price}")
    price_keys = ["product_id", "date"]
    if prices[price_keys].isna().any().any() or prices.duplicated(price_keys).any():
        raise ValueError("price_history.csv must have unique, non-missing product/date keys")
    if not pd.to_numeric(prices["close"], errors="coerce").map(pd.notna).all():
        raise ValueError("price_history.csv close values must be numeric")
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
