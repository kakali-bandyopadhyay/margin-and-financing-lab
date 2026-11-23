"""Command line entry point for one deterministic MFL run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import duckdb
import numpy as np
import pandas as pd

from .attribution import attribute
from .calibrate import run_calibration
from .exhibits import all_in_cost, euler_allocation, resolve_usage
from .io import Case, load_case, write_csv
from .margin import margin_detail
from .optimise import optimise
from .report import build, build_calib
from .stress import run_scenarios, write_outputs


def _git_head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _failure_report(run_dir: Path, status: str, slack_blocks: set[str]) -> None:
    results_dir = run_dir / "results"
    write_csv(pd.DataFrame([{"status": status, "slack_blocks": ",".join(sorted(slack_blocks))}]), results_dir / "status.csv")
    banner = f"{status}: {', '.join(sorted(slack_blocks)) or 'no slack block identified'}"
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Run status</title>"
        "<style>body{font:13px system-ui,sans-serif;margin:32px}.status{padding:16px;background:#fee;color:#900;border:1px solid #c00}</style>"
        f"</head><body><div class=\"status\">{banner}</div></body></html>"
    )
    (run_dir / "report.html").write_text(document, encoding="utf-8", newline="\n")


def _scenario_frames(case: Case, name: str):
    book, rates, providers = case.book.copy(), case.rates.copy(), case.providers.copy()
    ell = None
    if name == "vol_bucket_plus1":
        book["vol_bucket"] = book["vol_bucket"].replace({"V1": "V2", "V2": "V3"})
    elif name == "base_rate_x1.25":
        rates["base_rate"] *= 1.25
    elif name == "theta_0.20":
        providers["conc_threshold"] = 0.20
    elif name == "theta_0.30":
        providers["conc_threshold"] = 0.30
    elif name.startswith("ell_"):
        ell = float(name.split("_")[1])
    return book, rates, providers, ell


def _sensitivity(case: Case, pm_ids: list[object], base):
    names = ["base", "vol_bucket_plus1", "base_rate_x1.25", "theta_0.20", "theta_0.30", "ell_100", "ell_300", "ell_500"]
    summary, by_pb, by_pm = [], [], []
    for name in names:
        book, rates, providers, ell = _scenario_frames(case, name)
        result = base if name == "base" else optimise(book, rates, providers, case.borrow.copy(), case.params, ell_bps=ell)
        if result.status != "optimal":
            summary.append({"scenario": name, "status": result.status, "objective_usd": np.nan, "financing_usd": np.nan,
                            "margin_funding_usd": np.nan, "total_margin_usd": np.nan, "total_charge_usd": np.nan})
            for pb_id in case.providers["pb_id"]:
                by_pb.append({"scenario": name, "pb_id": pb_id, "margin_usd": np.nan, "gross_usd": np.nan})
            for pm_id in pm_ids:
                by_pm.append({"scenario": name, "pm_id": pm_id, "attributed_margin_usd": np.nan, "charge_usd": np.nan})
            continue
        attributed = attribute(book, result.w, rates, providers, case.params, pm_ids=pm_ids)
        margin = result.margin_by_pb.set_index("pb_id")["margin_usd"]
        gross = (book["notional_usd"].to_numpy()[:, None] * result.w).sum(axis=0)
        for i, pb_id in enumerate(providers["pb_id"]):
            by_pb.append({"scenario": name, "pb_id": pb_id, "margin_usd": float(margin.loc[pb_id]), "gross_usd": float(gross[i])})
        by_pm.extend({"scenario": name, **row} for row in attributed[["pm_id", "attributed_margin_usd", "charge_usd"]].to_dict("records"))
        summary.append({"scenario": name, "status": result.status, "objective_usd": result.objective_usd,
                        "financing_usd": result.financing_usd, "margin_funding_usd": result.margin_funding_usd,
                        "total_margin_usd": float(margin.sum()), "total_charge_usd": float(attributed["charge_usd"].sum())})
    return pd.DataFrame(summary), pd.DataFrame(by_pb), pd.DataFrame(by_pm)


def run(seed: int, data_dir: Path, out_dir: Path) -> int:
    case = load_case(data_dir)
    case.params["seed"] = int(seed)
    run_dir = Path(out_dir) / f"run_{seed}"
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    base = optimise(case.book, case.rates, case.providers, case.borrow, case.params)
    if base.status != "optimal":
        _failure_report(run_dir, base.status, base.slack_blocks)
        print(run_dir / "report.html")
        return 2

    pm_ids = case.pms["pm_id"].tolist()
    attributed = attribute(case.book, base.w, case.rates, case.providers, case.params, pm_ids=pm_ids)
    resolved = resolve_usage(case.book, case.rates, case.providers, case.borrow, case.params, base)
    all_in = all_in_cost(case.book, base.w, case.rates, case.borrow, case.providers, case.params, attributed)
    euler, kinks = euler_allocation(case.book, base.w, case.rates, case.providers, case.params, pm_ids=pm_ids)
    family, issuer = margin_detail(case.book, base.w, case.rates, case.providers, case.params)
    n = case.book["notional_usd"].to_numpy(dtype=float)
    allocations = pd.DataFrame([
        {"pos_id": pos_id, "pb_id": pb_id, "w": float(base.w[i, j]), "notional_alloc_usd": float(n[i] * base.w[i, j])}
        for i, pos_id in enumerate(case.book["pos_id"]) for j, pb_id in enumerate(case.providers["pb_id"])
    ])
    margin_total = float(base.margin_by_pb["margin_usd"].sum())
    summary = pd.DataFrame([{
        "status": base.status, "objective_usd": base.objective_usd, "financing_usd": base.financing_usd,
        "margin_funding_usd": base.margin_funding_usd, "total_margin_usd": margin_total,
        "horizon_days": case.params["horizon_days"], "ell_bps": case.params["liquidity_premium_bps"],
        "pass_through_bps": case.params["pass_through_bps"], "seed": seed,
    }])
    outputs = {
        "positions_alloc": allocations, "margin_by_pb": base.margin_by_pb,
        "margin_family": family, "margin_issuer": issuer,
        "duals_capacity": base.duals["capacity"], "duals_counterparty": base.duals["counterparty"],
        "duals_borrow": base.duals["borrow"], "attribution": attributed, "resolve": resolved,
        "all_in": all_in, "euler": euler, "kinks": kinks,
        "run_summary": summary,
    }
    sensitivity_summary, sensitivity_pb, sensitivity_pm = _sensitivity(case, pm_ids, base)
    outputs.update({"sensitivity_summary": sensitivity_summary, "sensitivity_pb": sensitivity_pb, "sensitivity_pm": sensitivity_pm})
    for name, frame in outputs.items():
        write_csv(frame, results_dir / f"{name}.csv")
    build(run_dir, case)
    meta = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_head": _git_head(),
            "python_version": sys.version.split()[0], "duckdb_version": duckdb.__version__}
    (run_dir / "run_meta.json").write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(run_dir / "report.html")
    return 0


def stress(seed: int, data_dir: Path, out_dir: Path) -> int:
    if not (data_dir / "params.csv").is_file() and (data_dir / "raw").is_dir():
        data_dir = data_dir / "raw"
    case = load_case(data_dir)
    case.params["seed"] = int(seed)
    result = run_scenarios(case, data_dir=data_dir)
    write_outputs(result, out_dir)

    run_dir = Path(out_dir).parent / f"run_{seed}"
    if (run_dir / "results" / "run_summary.csv").is_file():
        build(run_dir, case, stress_dir=Path(out_dir))
        print(run_dir / "report.html")
    else:
        print(Path(out_dir))
    return 0


def calibrate(seed: int, data_dir: Path, raw_dir: Path, out_dir: Path) -> int:
    """Run Phase 2b calibration into a separate output directory."""
    case_dir = data_dir
    if not (case_dir / "params.csv").is_file() and (case_dir / "raw").is_dir():
        case_dir = case_dir / "raw"
    case = load_case(case_dir)
    case.params["seed"] = int(seed)
    run_calibration(case, raw_dir, out_dir)
    report_path = build_calib(out_dir, case)
    print(report_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mfl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("run")
    command.add_argument("--seed", type=int, default=42)
    command.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    command.add_argument("--out", type=Path, default=Path("reports"))
    stress_command = subparsers.add_parser("stress")
    stress_command.add_argument("--seed", type=int, default=42)
    stress_command.add_argument("--data", type=Path, default=Path("data"))
    stress_command.add_argument("--out", type=Path, default=Path("reports/stress_42"))
    calibrate_command = subparsers.add_parser("calibrate")
    calibrate_command.add_argument("--seed", type=int, default=42)
    calibrate_command.add_argument("--data", type=Path, default=Path("data"))
    calibrate_command.add_argument("--raw", type=Path, default=Path("data/public/raw"))
    calibrate_command.add_argument("--out", type=Path, default=Path("reports/calib_42"))
    args = parser.parse_args(argv)
    if args.command == "stress":
        return stress(args.seed, args.data, args.out)
    if args.command == "calibrate":
        return calibrate(args.seed, args.data, args.raw, args.out)
    return run(args.seed, args.data_dir, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
