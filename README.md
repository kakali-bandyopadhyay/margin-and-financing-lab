# margin-and-financing-lab

[![CI](https://github.com/kakali-bandyopadhyay/margin-and-financing-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/kakali-bandyopadhyay/margin-and-financing-lab/actions/workflows/ci.yml)

**Boundary.** This is a personal build on synthetic data. It is not a portfolio-margin model and is not calibrated to any prime broker, exchange or clearing house: the margin proxy uses stated rates, volatility buckets and a simple per-broker offset rule, so offsets are approximated. The internal charge policy is illustrative. Outputs describe how the model behaves under its stated assumptions; they are not predictions, not any firm's methodology, and the model is not validated. Any production use would need independent model validation and Treasury, Risk and Legal review.

## What it does
Allocates a synthetic multi-asset hedge-fund book across synthetic prime brokers at minimum financing-plus-margin-funding cost over a stated horizon, subject to capacity, counterparty and borrow limits, then attributes margin usage and an illustrative charge to portfolio managers.

## Status
Phase 1 complete: margin proxy (M1), allocation optimiser (M2), PM usage attribution and illustrative charge (M3), exhibits, and a DuckDB/HTML report. Model, tests and expected behaviour were pre-registered before any model code ([`prereg/PREREGISTRATION.md`](prereg/PREREGISTRATION.md)); eight logged deviations ([`prereg/DEVIATIONS.md`](prereg/DEVIATIONS.md)). Primary run (seed 42) reported in full in [`RESULTS.md`](RESULTS.md), outputs in [`reports/run_42/`](reports/run_42/). Phase 2a adds static prime-broker stress plumbing; the separate synthetic calibration exercise and MILP variant remain unstarted. The model is not validated.

## Quickstart
```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -W error -q
python -m mfl.cli run --seed 42 --out reports/local   # writes reports/local/run_42/ (git-ignored); compare with the committed reports/run_42/
```

## Phase 2a – stress projection
The stress command writes the pre-registered scenario CSVs to `reports/stress_42/` and adds a summary and top-10 moves section to the existing run report. This is an illustrative static prime-broker margin and funding projection over 90 days: it is not calibrated and is not any firm's methodology. Cleared or exchange margin, path dependence and margin-call dynamics are out of scope. The additional funding requirement is an absolute increase against ST0 plus constraint slack, with no available-liquidity or buffer term; it is not a liquidity-coverage gap.

## Documents
- [`docs/MODEL_DOC.md`](docs/MODEL_DOC.md) – model documentation (purpose, methodology, limitations, validation status)
- [`docs/HAND_WORKED_EXAMPLE.md`](docs/HAND_WORKED_EXAMPLE.md) – the two cases the tests check to the cent
- [`RESULTS.md`](RESULTS.md) – primary run, E1–E5 confirmed / not confirmed
- [`S1_GUIDE.md`](S1_GUIDE.md) – step-by-step build guide
- [`data/SOURCES.md`](data/SOURCES.md) – data provenance
