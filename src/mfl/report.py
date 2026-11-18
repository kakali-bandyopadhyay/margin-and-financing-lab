"""Deterministic static HTML report rendered from DuckDB query results."""

from __future__ import annotations

import html
from pathlib import Path
import re

import duckdb
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


def _fmt(value: object, column: str) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if column.endswith("pct") or column in {"share", "offset_ratio"}:
            return f"{value:,.2f}%" if column.endswith("pct") else f"{value:,.2f}"
        if column.endswith("usd") or column.endswith("_usd") or column in {"r", "phi"}:
            return f"{value:,.2f}"
        return f"{value:,.2f}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _table(frame: pd.DataFrame) -> str:
    headers = "".join(f"<th>{html.escape(str(c))}</th>" for c in frame.columns)
    body = []
    for row in frame.itertuples(index=False, name=None):
        cells = "".join(
            f'<td class="num">{html.escape(_fmt(value, str(col)))}</td>'
            for col, value in zip(frame.columns, row, strict=True)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def build(run_dir: Path, case: Case) -> None:
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
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>margin-and-financing-lab – run report</title>"
        "<style>body{font:13px system-ui,sans-serif;max-width:1280px;margin:32px auto;padding:0 20px;color:#20242a}"
        "h1,h2{font-weight:600}section{margin:30px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}"
        "th,td{padding:7px 9px;border-bottom:1px solid #d9dde2;text-align:left}th{background:#f1f3f5}"
        "tbody tr:nth-child(even){background:#f8f9fa}.num{text-align:right}.note{font-style:italic;color:#555}footer{margin-top:38px;color:#555}</style></head><body>"
        f"<h1>margin-and-financing-lab – run report (seed {seed})</h1><p>{html.escape(_boundary())}</p>"
        f"<section><h2>Run summary</h2>{summary_html}</section>{''.join(rendered)}"
        "<footer>Synthetic data. Illustrative charge policy. Not validated.</footer></body></html>"
    )
    (run_dir / "report.html").write_text(document, encoding="utf-8", newline="\n")
    db.close()
