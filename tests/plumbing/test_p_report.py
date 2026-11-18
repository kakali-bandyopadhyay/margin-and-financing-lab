from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


RESULTS = [
    "positions_alloc", "margin_by_pb", "margin_family", "margin_issuer", "duals_capacity",
    "duals_counterparty", "duals_borrow", "attribution", "resolve", "all_in", "euler",
    "kinks", "sensitivity_summary", "sensitivity_pb", "sensitivity_pm", "run_summary",
]
TABLES = [
    "10_allocation_by_pb", "20_margin_by_pb", "21_margin_by_family", "22_margin_by_issuer",
    "30_constraints", "40_pm_usage_charge", "41_pm_exhibits", "42_kinks", "42_kinks_count", "50_sensitivity",
]


@pytest.fixture(scope="module")
def run_output(tmp_path_factory):
    target = tmp_path_factory.mktemp("mfl_run")
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "mfl.cli", "run", "--seed", "42", "--data-dir", str(root / "data" / "raw"), "--out", str(target)],
        cwd=root, text=True, capture_output=True,
    )
    return completed, target / "run_42"


def test_p5_cli_outputs_exist(run_output):
    completed, run_dir = run_output
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (run_dir / "report.html").is_file()
    assert all((run_dir / "results" / f"{name}.csv").is_file() for name in RESULTS)
    assert all((run_dir / "tables" / f"{name}.csv").is_file() for name in TABLES)


def test_p6_step5_reference_values(run_output):
    _, run_dir = run_output
    summary = pd.read_csv(run_dir / "results" / "run_summary.csv").iloc[0]
    assert summary["objective_usd"] == pytest.approx(21_714_337.24, abs=0.01)
    assert summary["total_margin_usd"] == pytest.approx(1_747_690_859.46, abs=0.01)
    kinks = pd.read_csv(run_dir / "results" / "kinks.csv")
    assert int(kinks["kind"].eq("net").sum()) == 40
    assert int(kinks["kind"].eq("hinge").sum()) == 0
    counts = pd.read_csv(run_dir / "tables" / "42_kinks_count.csv").set_index("kind")["kink_count"]
    assert counts.to_dict() == {"hinge": 0, "net": 40}


def test_p7_sql_reconciles_and_slacks_are_nonnegative(run_output):
    _, run_dir = run_output
    results = run_dir / "results"
    alloc = pd.read_csv(results / "positions_alloc.csv")
    pos = pd.read_csv(Path(__file__).resolve().parents[2] / "data" / "raw" / "positions.csv")
    expected_gross = pos["notional_usd"].sum()
    tables = run_dir / "tables"
    margin = pd.read_csv(tables / "20_margin_by_pb.csv")
    attributed = pd.read_csv(tables / "40_pm_usage_charge.csv")
    constraints = pd.read_csv(tables / "30_constraints.csv")
    M = pd.read_csv(results / "run_summary.csv").iloc[0]["total_margin_usd"]
    assert margin["margin_usd"].sum() == pytest.approx(M, abs=1e-6)
    total = attributed.loc[attributed["pm_id"].eq("TOTAL")].iloc[0]
    tolerance = 1e-6 * max(1.0, M)
    attribution = pd.read_csv(results / "attribution.csv")
    assert abs(attribution["attributed_margin_usd"].sum() - M) <= tolerance
    assert abs(total["sum_attributed_minus_M"]) <= tolerance
    assert abs(attribution["share"].sum() - 1.0) <= 1e-9
    assert pd.read_csv(tables / "10_allocation_by_pb.csv")["gross_usd"].sum() == pytest.approx(expected_gross, abs=1e-6)
    assert (constraints["slack_usd"] >= -1e-6).all()


def test_p8_second_run_is_byte_identical(run_output, tmp_path):
    _, first = run_output
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "mfl.cli", "run", "--seed", "42", "--data-dir", str(root / "data" / "raw"), "--out", str(tmp_path)],
        cwd=root, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    second = tmp_path / "run_42"
    for name in ["report.html", *[f"results/{n}.csv" for n in RESULTS], *[f"tables/{n}.csv" for n in TABLES]]:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_p9_report_and_csvs_are_neutral(run_output):
    _, run_dir = run_output
    files = [run_dir / "report.html", *list((run_dir / "results").glob("*.csv")), *list((run_dir / "tables").glob("*.csv"))]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for forbidden in ("W:\\", "C:\\"):
        assert forbidden.casefold() not in text.casefold()


def test_p10_sensitivity_scenarios(run_output):
    _, run_dir = run_output
    data = pd.read_csv(run_dir / "results" / "sensitivity_summary.csv").set_index("scenario")
    assert len(data) == 8
    assert set(data["status"].notna()) == {True}
    for column in ("objective_usd", "financing_usd", "margin_funding_usd", "total_margin_usd", "total_charge_usd"):
        assert data.loc["ell_100", column] == pytest.approx(data.loc["base", column], abs=1e-6)
