from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from mfl.report import _stress_section


SCENARIOS = {"ST0", "ST1a", "ST1b", "ST2a", "ST2b", "ST3", "ST4"}
EXPECTED_COLUMNS = {
    "stress_summary.csv": [
        "scenario", "cost_window_start", "total_margin_usd", "delta_margin_usd",
        "financing_cost_usd", "delta_financing_cost_usd", "margin_funding_cost_usd",
        "delta_margin_funding_cost_usd", "status", "slack_capacity_usd",
        "slack_counterparty_usd", "slack_borrow_usd", "total_slack_usd",
        "additional_funding_requirement_usd", "terminated_pb", "notice_days",
        "nav_trigger_pct", "notional_to_move_usd",
    ],
    "stress_margin_by_pb.csv": [
        "scenario", "pb_id", "margin_usd", "gross_usd", "capacity_usd", "utilisation_pct",
    ],
    "stress_moves.csv": ["scenario", "pos_id", "from_pb", "to_pb", "notional_moved_usd"],
    "stress_st3_netting.csv": [
        "scenario", "pb_id", "role", "margin_with_offsets_usd", "margin_without_offsets_usd",
        "netting_benefit_usd", "st0_margin_with_offsets_usd", "st0_margin_without_offsets_usd",
        "st0_netting_benefit_usd", "netting_change_usd", "reallocation_effect_usd",
        "delta_margin_vs_st0_usd", "identity_residual_usd",
    ],
    "stress_bucket_sensitivity.csv": [
        "scenario", "cut_low", "cut_high", "total_margin_usd", "delta_margin_vs_st0_usd", "status",
    ],
}


def test_stress_cli_writes_registered_outputs_and_report_section(tmp_path, repo_root):
    stress_dir = tmp_path / "reports" / "stress_42"
    completed = subprocess.run(
        [
            sys.executable, "-m", "mfl", "stress", "--seed", "42",
            "--data", "data", "--out", str(stress_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    for name, columns in EXPECTED_COLUMNS.items():
        path = stress_dir / name
        assert path.is_file()
        assert list(pd.read_csv(path).columns) == columns

    summary = pd.read_csv(stress_dir / "stress_summary.csv")
    assert len(summary) == 7
    assert set(summary["scenario"]) == SCENARIOS
    report = _stress_section(stress_dir)
    assert "Stress projection (Phase 2a)" in report
    assert "Top 10 moves" in report

