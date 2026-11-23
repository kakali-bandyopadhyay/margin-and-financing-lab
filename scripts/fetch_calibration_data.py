"""Fetch the pre-registered public proxy inputs for Phase 2b.

Run only after the Phase 2b preregistration is committed and tagged.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from mfl.calib_data import canonical_raw_bytes, digest_row


REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_MAP = REPO_ROOT / "data" / "public" / "calibration_proxies.csv"
DIGEST_PATH = REPO_ROOT / "data" / "public" / "calibration_inputs_digest.csv"
DIGEST_COLUMNS = [
    "symbol", "source", "field", "first_date", "last_date", "rows",
    "sha256_raw", "sha256_returns", "fetch_date",
]


def _dotenv_value(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value.strip() or None
    return None


def _read_response(request: Request, label: str) -> str:
    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"{label} request failed with HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{label} request failed: {type(exc).__name__}") from None


def _normalize(rows: list[dict[str, str]], date_field: str, value_field: str) -> pd.DataFrame:
    cleaned = []
    for row in rows:
        raw_date = row.get(date_field)
        raw_value = row.get(value_field)
        if raw_date is None or raw_value is None:
            continue
        value_text = str(raw_value).strip()
        if not value_text or value_text == ".":
            continue
        cleaned.append({
            "date": pd.Timestamp(raw_date).date().isoformat(),
            "value": float(value_text),
        })
    frame = pd.DataFrame(cleaned, columns=["date", "value"])
    if frame.empty:
        raise RuntimeError("source returned no valid observations in the requested date range")
    frame = frame.sort_values("date", kind="mergesort").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise RuntimeError("source returned duplicate observation dates")
    if not pd.to_numeric(frame["value"], errors="coerce").map(pd.notna).all():
        raise RuntimeError("source returned a nonnumeric observation")
    return frame


def fetch_tiingo(symbol: str, start: str, end: str, api_key: str) -> pd.DataFrame:
    query = urlencode({"startDate": start, "endDate": end, "format": "csv"})
    url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices?{query}"
    request = Request(url, headers={"Authorization": f"Token {api_key}", "Accept": "text/csv"})
    text = _read_response(request, f"Tiingo {symbol}")
    rows = list(csv.DictReader(StringIO(text)))
    if not rows or "adjClose" not in rows[0]:
        raise RuntimeError(f"Tiingo {symbol} response did not include adjClose data")
    return _normalize(rows, "date", "adjClose")


def fetch_fred(symbol: str, start: str, end: str) -> pd.DataFrame:
    query = urlencode({"id": symbol, "cosd": start, "coed": end})
    request = Request(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?{query}",
        headers={"Accept": "text/csv"},
    )
    text = _read_response(request, f"FRED {symbol}")
    rows = list(csv.DictReader(StringIO(text)))
    if not rows:
        raise RuntimeError(f"FRED {symbol} response was empty")
    date_field = "observation_date" if "observation_date" in rows[0] else "DATE"
    value_field = symbol if symbol in rows[0] else next(
        (field for field in rows[0] if field != date_field), None
    )
    if value_field is None:
        raise RuntimeError(f"FRED {symbol} response did not include a value column")
    return _normalize(rows, date_field, value_field)


def _duration(value: object, symbol: str) -> float:
    if symbol != "DGS10":
        return 0.0
    try:
        duration = float(value)
    except (TypeError, ValueError):
        raise RuntimeError("DGS10 duration is still TBD-KAKALI; complete the preregistered value before fetching") from None
    if duration <= 0:
        raise RuntimeError("DGS10 duration must be positive")
    return duration


def write_digest(
    proxy_map: pd.DataFrame,
    fetched: dict[str, pd.DataFrame],
    fetch_date: str,
    destination: Path,
) -> pd.DataFrame:
    """Write one canonical digest record per unique proxy symbol, sorted."""
    digest_records = []
    for symbol in sorted(proxy_map["proxy_symbol"].astype(str).unique()):
        symbol_rows = proxy_map.loc[proxy_map["proxy_symbol"].astype(str).eq(symbol)]
        variants = symbol_rows[["source", "return_type", "duration"]].drop_duplicates()
        if len(variants) != 1:
            raise RuntimeError(f"proxy symbol {symbol} has conflicting source or return definitions")
        row = variants.iloc[0]
        frame = fetched[symbol].copy()
        if row["return_type"] == "dgs10_price_return":
            frame.attrs["return_type"] = "dgs10_price_return"
            frame.attrs["duration"] = _duration(row["duration"], symbol)
        digest_records.append(
            digest_row(
                symbol,
                row["source"],
                "adjClose" if row["source"] == "Tiingo" else symbol,
                frame,
                fetch_date,
            )
        )
    digest = pd.DataFrame(digest_records, columns=DIGEST_COLUMNS)
    digest.to_csv(destination, index=False, float_format="%.17g", lineterminator="\n", encoding="utf-8")
    return digest


def fetch(start: str, end: str, out_dir: Path) -> None:
    proxy_map = pd.read_csv(PROXY_MAP, dtype=str, keep_default_na=False)
    required = {"product_type", "proxy_symbol", "source", "return_type", "duration"}
    if not required.issubset(proxy_map.columns) or len(proxy_map) != 7:
        raise RuntimeError("calibration_proxies.csv must contain the seven pre-registered proxy rows")

    expected_out = (REPO_ROOT / "data" / "public" / "raw").resolve()
    if out_dir.resolve() != expected_out:
        raise RuntimeError("output directory must be data/public/raw so vendor prices remain git-ignored")

    tiingo_symbols = sorted(set(proxy_map.loc[proxy_map["source"].eq("Tiingo"), "proxy_symbol"]))
    api_key = _dotenv_value(REPO_ROOT / ".env", "TIINGO_API_KEY") if tiingo_symbols else None
    if tiingo_symbols and not api_key:
        raise RuntimeError("TIINGO_API_KEY is missing from the repository .env file")

    out_dir.mkdir(parents=True, exist_ok=True)
    fred_dir = REPO_ROOT / "data" / "public" / "fred"
    fred_dir.mkdir(parents=True, exist_ok=True)
    fetch_date = datetime.now(timezone.utc).date().isoformat()
    fetched: dict[str, pd.DataFrame] = {}

    for symbol, source in (
        proxy_map[["proxy_symbol", "source"]].drop_duplicates().sort_values("proxy_symbol").itertuples(index=False, name=None)
    ):
        if source == "Tiingo":
            frame = fetch_tiingo(symbol, start, end, api_key or "")
        elif source == "FRED":
            frame = fetch_fred(symbol, start, end)
        else:
            raise RuntimeError(f"unsupported proxy source for {symbol}")
        fetched[symbol] = frame
        (out_dir / f"{symbol}.csv").write_bytes(canonical_raw_bytes(frame))
        if source == "FRED":
            (fred_dir / f"{symbol}.csv").write_bytes(canonical_raw_bytes(frame))

    write_digest(proxy_map, fetched, fetch_date, DIGEST_PATH)
    print(f"Fetched {len(fetched)} proxy series; digest written to {DIGEST_PATH.name}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Phase 2b calibration proxy data")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        start = date.fromisoformat(args.start).isoformat()
        end = date.fromisoformat(args.end).isoformat()
        if start > end:
            parser.error("--start must be on or before --end")
        fetch(start, end, args.out if args.out.is_absolute() else REPO_ROOT / args.out)
    except RuntimeError as exc:
        parser.exit(2, f"fetch failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
