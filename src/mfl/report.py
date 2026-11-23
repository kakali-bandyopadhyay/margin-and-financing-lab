"""Deterministic static HTML report rendered from DuckDB query results."""

from __future__ import annotations

import html
from pathlib import Path
import re

import duckdb
import numpy as np
import pandas as pd

from .io import Case, write_csv


QUERIES = [
    ("10_allocation_by_pb", "Allocation by prime broker", "Gross, long, short and net allocated notional with capacity usage."),
    ("20_margin_by_pb", "Margin by prime broker", "Buffered margin, counterparty limit, headroom and share of total margin."),
    ("21_margin_by_family", "Margin by family", "Family margin and exposure by product, liquidity tier and volatility bucket."),
    ("22_margin_by_issuer", "Margin by issuer", "Positive concentration add-ons and issuer share of prime broker gross."),
    ("30_constraints", "Constraints and duals", "Capacity, counterparty and borrow limits, usage, slack and solver duals."),
    ("40_pm_usage_charge", "PM usage and charge", "Fixed-allocation usage, attributed margin, charge and total check."),
    ("41_pm_exhibits", "PM exhibits", "Re-solve usage, objective change, all-in cost, Euler values and attributed margin."),
    ("42_kinks", "Kinks", "Euler kink records."),
    ("42_kinks_count", "Kink counts", "Counts of net and hinge kinks."),
    ("50_sensitivity", "Sensitivity", "Scenario totals and differences from the base scenario."),
]


def _boundary() -> str:
    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\*\*Boundary\.\*\*.*(?:\n(?!\n).*)*", text)
    if not match:
        raise ValueError("README.md is missing the Boundary paragraph")
    return match.group(0).replace("**", "")


def _fmt(value: object, column: str, dtype: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "Yes" if value else "No"
    if isinstance(value, (int, float, np.integer, np.floating)):
        if pd.api.types.is_integer_dtype(dtype) or column.endswith("_count"):
            return f"{int(value):,}"
        if column in {"r", "phi", "conc_rate"}:
            return f"{value:,.4f}"
        if column in {"share", "offset_ratio", "issuer_share_pb_gross"}:
            return f"{value * 100:,.2f}%"
        if column.endswith("_pct"):
            return f"{value:,.2f}%"
        return f"{value:,.2f}"
    return str(value)


def _table(frame: pd.DataFrame) -> str:
    numeric = {
        column: pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
        for column, dtype in frame.dtypes.items()
    }
    headers = "".join(
        f'<th class="{"num" if numeric[column] else "text"}">{html.escape(str(column))}</th>'
        for column in frame.columns
    )
    body = []
    for row in frame.itertuples(index=False, name=None):
        cells = "".join(
            f'<td class="{"num" if numeric[col] else "text"}">{html.escape(_fmt(value, str(col), frame[col].dtype))}</td>'
            for col, value in zip(frame.columns, row, strict=True)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _stress_section(stress_dir: Path) -> str:
    summary_path = stress_dir / "stress_summary.csv"
    moves_path = stress_dir / "stress_moves.csv"
    if not summary_path.is_file() or not moves_path.is_file():
        return ""
    summary = pd.read_csv(summary_path)
    moves = pd.read_csv(moves_path)
    if "notional_moved_usd" in moves.columns and len(moves):
        moves = moves.sort_values(
            ["notional_moved_usd", "scenario", "pos_id"],
            ascending=[False, True, True],
            kind="mergesort",
        ).head(10)
    return (
        "<section><h2>Stress projection (Phase 2a)</h2>"
        "<p>Illustrative static stress projection over the 90-day horizon; not calibrated and not any firm's methodology. "
        "Cleared and exchange margin, path dependence and margin-call dynamics are out of scope.</p>"
        f"<h3>Scenario summary</h3>{_table(summary)}"
        f"<h3>Top 10 moves</h3>{_table(moves)}</section>"
    )


def build(run_dir: Path, case: Case, stress_dir: Path | None = None) -> None:
    run_dir = Path(run_dir)
    results_dir, tables_dir = run_dir / "results", run_dir / "tables"
    db = duckdb.connect(database=":memory:")
    raw = {
        **case.raw_tables,
        "pms": case.pms,
        "providers": case.providers,
        "pb_rates": case.rates,
        "pb_borrow": case.borrow,
    }
    for name, frame in raw.items():
        db.register(name, frame)
    result_frames = {}
    for path in sorted(results_dir.glob("*.csv")):
        name = path.stem
        frame = pd.read_csv(path)
        result_frames[name] = frame
        db.register(name, frame)
    db.execute((Path(__file__).resolve().parents[2] / "sql" / "00_views.sql").read_text(encoding="utf-8"))
    rendered = []
    for stem, title, caption in QUERIES:
        frame = db.execute((Path(__file__).resolve().parents[2] / "sql" / f"{stem}.sql").read_text(encoding="utf-8")).df()
        write_csv(frame, tables_dir / f"{stem}.csv")
        note = '<p class="note">Duals: sensitivity only; may be non-unique under degeneracy.</p>' if stem == "30_constraints" else ""
        rendered.append(f"<section><h2>{html.escape(title)}</h2><p>{html.escape(caption)}</p>{note}{_table(frame)}</section>")
    summary = result_frames["run_summary"].iloc[0]
    summary_html = _table(pd.DataFrame([summary]))
    seed = int(summary["seed"])
    stress_html = _stress_section(Path(stress_dir)) if stress_dir is not None else ""
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>margin-and-financing-lab – run report</title>"
        "<style>body{font:13px system-ui,sans-serif;max-width:1280px;margin:32px auto;padding:0 20px;color:#20242a}"
        "h1,h2{font-weight:600}section{margin:30px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}"
        "th,td{padding:7px 9px;border-bottom:1px solid #d9dde2}th{background:#f1f3f5}"
        "tbody tr:nth-child(even){background:#f8f9fa}.num{text-align:right}.text{text-align:left}.note{font-style:italic;color:#555}footer{margin-top:38px;color:#555}</style></head><body>"
        f"<h1>margin-and-financing-lab – run report (seed {seed})</h1><p>{html.escape(_boundary())}</p>"
        f"<section><h2>Run summary</h2>{summary_html}</section>{''.join(rendered)}{stress_html}"
        "<footer>Synthetic data. Illustrative charge policy. Not validated.</footer></body></html>"
    )
    (run_dir / "report.html").write_text(document, encoding="utf-8", newline="\n")
    db.close()
