# RESULTS – margin-and-financing-lab, primary run (seed 42)

Run: `python -m mfl.cli run --seed 42` at commit `4fa2e37` · Python 3.14.7 · DuckDB 2.0.0 · HiGHS 1.16.0 · run timestamp 2026-11-18T16:18:39 UTC.  
Tests at this commit: 81 passed (`python -m pytest -W error -q`); CI green.  
Every number below is copied by script from the run's CSVs in `reports/run_42/` (`results/` and `tables/`); none are typed by hand. The primary run's outputs are committed in [`reports/run_42/`](reports/run_42/) (`run_meta.json`, `report.html`, `results/`, `tables/`); rerunning the command above regenerates them. Model, parameters and expected behaviour were fixed in advance in [`prereg/PREREGISTRATION.md`](prereg/PREREGISTRATION.md); departures are in [`prereg/DEVIATIONS.md`](prereg/DEVIATIONS.md). How to read these numbers, and what they are not, is in [`docs/MODEL_DOC.md`](docs/MODEL_DOC.md). Synthetic data; illustrative charge policy; not validated.

Reproducibility: this run's 26 output CSVs are byte-identical to an earlier run of the same data at commit `ddc2f32` (the commits in between changed load-time validation in `io.py`, report display in `report.py`, documentation and tests; M1–M3 and exhibit code are unchanged).

## 1. Primary run – headline

| Item | Value |
|---|---|
| Objective (financing + margin funding), USD over H | 21,714,337 |
| Financing cost, USD | 17,345,110 |
| Margin funding cost, USD | 4,369,227 |
| Total margin M, USD | 1,747,690,859 |
| Solver status | optimal |
| Horizon H / ℓ / pass-through | 90 days / 100 bps / 100 bps |

## 2. Allocation and margin by prime broker
Source: `tables/10_allocation_by_pb.csv`, `results/margin_by_pb.csv`, `tables/30_constraints.csv`.

| PB | Positions held (any share) | Gross USD m | Long USD m | Short USD m | Capacity used | Margin USD m | Counterparty limit USD m | Margin / limit |
|---|---|---|---|---|---|---|---|---|
| PB_A | 80 | 1,930.67 | 1,010.38 | 920.28 | 55.4% | 477.12 | 702.21 | 67.9% |
| PB_B | 49 | 1,085.38 | 560.21 | 525.16 | 55.8% | 211.73 | 211.73 | 100.0% |
| PB_C | 56 | 1,510.85 | 703.27 | 807.57 | 54.7% | 293.93 | 469.18 | 62.6% |
| PB_D | 106 | 2,912.03 | 2,098.22 | 813.80 | 73.8% | 764.91 | 831.91 | 91.9% |

All four PBs are used. 49 of 214 positions are split across more than one PB.

## 3. Binding constraints and duals (sensitivity only)
Source: `tables/30_constraints.csv`. Duals are USD of objective per USD of limit; they are sensitivity signals and may be non-unique under degeneracy.

- Capacity: binding at 0 of 4 PBs.
- Counterparty: binding at PB_B (limit 211,730,389), dual 0.002061; slack at the other 3 PBs.
- Borrow: 176 PB × issuer rows; 14 have no locate (limit 0, w fixed at 0); 48 limits above zero bind, all with a positive dual (range 0.000009 to 0.021976; highest at PB_A / ISS015).

## 4. Margin by family and issuer
Source: `results/margin_family.csv`, `results/margin_issuer.csv`.

- 356 PB × family rows; family margin before buffer 1,519,526,081 USD.
- Concentration add-on is positive in 1 of 152 PB × issuer rows: PB_B / ISS013 205,101 USD.
- Check: 1.15 × (family margin + add-ons) = 1,747,690,859 USD = M.

## 5. PM usage and illustrative charge (primary: fixed-allocation leave-one-out)
Source: `results/attribution.csv`, `tables/40_pm_usage_charge.csv`. Charge = attributed margin × pass-through × H/360.

| PM | Usage u_k USD m | Solo margin USD m | Residual share | Residual USD m | Attributed margin USD m | Charge USD |
|---|---|---|---|---|---|---|
| PM01 | 362.51 | 408.21 | 19.77% | 54.85 | 417.36 | 1,043,391 |
| PM02 | 110.10 | 244.35 | 11.83% | 32.83 | 142.93 | 357,325 |
| PM03 | 154.61 | 236.65 | 11.46% | 31.80 | 186.40 | 466,004 |
| PM04 | 115.96 | 123.95 | 6.00% | 16.65 | 132.62 | 331,545 |
| PM05 | 510.47 | 750.91 | 36.37% | 100.89 | 611.36 | 1,528,404 |
| PM06 | 102.16 | 121.04 | 5.86% | 16.26 | 118.43 | 296,064 |
| PM07 | 29.68 | 48.35 | 2.34% | 6.50 | 36.17 | 90,434 |
| PM08 | 10.17 | 11.30 | 0.55% | 1.52 | 11.69 | 29,226 |
| PM09 | 49.75 | 72.87 | 3.53% | 9.79 | 59.54 | 148,845 |
| PM10 | 24.88 | 46.98 | 2.28% | 6.31 | 31.20 | 77,990 |
| **Total** | 1,470.30 | 2,064.61 | 100% | 277.39 | 1,747.69 | 4,369,227 |

Residual R = M − Σu_k = 277,392,908 USD (15.9% of M). Σ attributed − M = 2.38e-07 USD.

## 6. Exhibits: re-solve usage, all-in cost, Euler
Source: `tables/41_pm_exhibits.csv`, `results/kinks.csv`, `tables/42_kinks_count.csv`. Re-solve usage removes the PM and re-optimises the rest (sensitivity exhibit, not the charge basis). Euler ranges are [low, high] at kinks.

| PM | Usage fixed USD m | Usage re-solve USD m | Δ objective without PM USD | Financing USD | Margin funding USD | All-in USD | Euler USD m [low, high] |
|---|---|---|---|---|---|---|---|
| PM01 | 362.51 | 362.63 | 7,772,005 | 6,811,090 | 1,043,391 | 7,854,481 | 389.93 [375.95, 403.91] |
| PM02 | 110.10 | 116.22 | 1,747,743 | 1,289,306 | 357,325 | 1,646,631 | 178.05 [115.23, 240.87] |
| PM03 | 154.61 | 171.56 | 1,725,517 | 1,195,930 | 466,004 | 1,661,935 | 192.13 [154.61, 229.65] |
| PM04 | 115.96 | 117.07 | 806,777 | 508,864 | 331,545 | 840,409 | 118.74 [115.96, 121.52] |
| PM05 | 510.47 | 518.93 | 7,483,429 | 5,562,629 | 1,528,404 | 7,091,033 | 619.44 [510.47, 728.41] |
| PM06 | 102.16 | 101.95 | 1,572,588 | 1,312,271 | 296,064 | 1,608,335 | 111.79 [103.67, 119.92] |
| PM07 | 29.68 | 30.78 | 302,581 | 206,454 | 90,434 | 296,888 | 29.68 [29.68, 29.68] |
| PM08 | 10.17 | 10.06 | 152,357 | 125,472 | 29,226 | 154,698 | 10.74 [10.65, 10.84] |
| PM09 | 49.75 | 49.75 | 368,406 | 244,036 | 148,845 | 392,882 | 69.30 [69.21, 69.39] |
| PM10 | 24.88 | 24.88 | 151,267 | 89,058 | 77,990 | 167,047 | 27.88 [27.88, 27.88] |

Σ Euler = 1,747,690,859 USD vs M = 1,747,690,859 USD. Kinks at the optimum: net = 40, hinge = 0 – the Euler split is not unique for PMs with positions in those families (see the ranges).

## 7. Sensitivity grid (each scenario re-optimised)
Source: `tables/50_sensitivity.csv`, `results/sensitivity_pb.csv`. Δ is versus base. `ell_100` equals base (ℓ = 100 bps in the primary run).

| Scenario | Status | Objective USD | Δ objective | Δ objective % | M USD m | Δ M USD m | Total charge USD |
|---|---|---|---|---|---|---|---|
| base | optimal | 21,714,337 | 0 | 0.00% | 1,747.69 | 0.00 | 4,369,227 |
| base_rate_x1.25 | optimal | 22,981,488 | 1,267,151 | 5.84% | 2,206.32 | 458.63 | 5,515,793 |
| ell_100 | optimal | 21,714,337 | 0 | 0.00% | 1,747.69 | 0.00 | 4,369,227 |
| ell_300 | optimal | 30,404,906 | 8,690,569 | 40.02% | 1,727.01 | -20.68 | 4,317,523 |
| ell_500 | optimal | 39,035,200 | 17,320,862 | 79.77% | 1,724.28 | -23.41 | 4,310,704 |
| theta_0.20 | optimal | 21,721,583 | 7,246 | 0.03% | 1,749.18 | 1.49 | 4,372,941 |
| theta_0.30 | optimal | 21,713,142 | -1,195 | -0.01% | 1,745.98 | -1.71 | 4,364,946 |
| vol_bucket_plus1 | optimal | 22,148,277 | 433,940 | 2.00% | 1,906.44 | 158.75 | 4,766,110 |

PBs whose margin sits at the counterparty limit, by scenario – base: PB_B; base_rate_x1.25: PB_A, PB_B, PB_D; ell_100: PB_B; ell_300: PB_B, PB_D; ell_500: PB_B, PB_D; theta_0.20: PB_B; theta_0.30: PB_B; vol_bucket_plus1: PB_B, PB_D.

## 8. Exchange-margin sanity check (A7 – sanity only, not calibration)

Product `IRSF_10Y` against CBOT ZNZ26 (outright non-HRP initial, 1,875 USD per contract, settlement 105.609375, multiplier 1,000; effective 2026-11-17, accessed 2026-11-18; [`data/public/exchange_margin.csv`](data/public/exchange_margin.csv)). Exchange initial margin = 1.775% of notional. Ratio = proxy margin as % of notional ÷ exchange margin as % of notional, for one position held in full at each PB. The band 0.5–4.0 was fixed before the CME figure was checked (D-06).

Ratios printed by `python -m pytest tests/acceptance/test_a7_exchange_sanity.py -s -q` at `4fa2e37` (1 passed):

| PB | Proxy ÷ exchange | Inside 0.5–4.0 |
|---|---|---|
| PB_A | 2.392 | yes |
| PB_B | 2.74 | yes |
| PB_C | 1.691 | yes |
| PB_D | 2.128 | yes |

The proxy sits above exchange initial margin at every PB. The check screens for scale and unit errors only; it does not change any rate.

## 9. Expected behaviour E1–E5 (prereg §9) – confirmed / not confirmed

Evidence computed from `data/raw/*.csv` and the run CSVs named in each row. A hedged family = a (product, liquidity tier) with both long and short positions in the book.

| ID | Expectation (prereg §9, abridged) | Result | Evidence |
|---|---|---|---|
| E1 | Hedged pairs inside a family sit at one PB unless capacity or borrow forces a split | **Not confirmed as stated** – the run doesn't isolate why families split | 11 of 26 hedged families sit at one PB; 15 are split. Capacity binds nowhere; in 15 of the 15 split families the short issuer has a binding borrow limit at one or more PBs, and the PB_B counterparty limit (not listed in the expectation) also binds. Which constraint causes each split is not tested; a re-solve with borrow limits relaxed would isolate it and has not been run (Phase 2). `positions_alloc.csv`, `30_constraints.csv` |
| E2 | At least one capacity or counterparty constraint binds; the cheapest PB on financing is not the sole PB used | **Confirmed** | Counterparty binds at PB_B; capacity binds at 0 PBs; all 4 PBs hold positions. `30_constraints.csv`, `10_allocation_by_pb.csv` |
| E3 | Shorts in issuers with locate at only one PB sit at that PB; tight locate shows a positive borrow dual | **Confirmed** | 3 issuers (ISS003, ISS005, ISS010) have locate at one PB only; all 7 short positions in them sit at that PB. None of those 3 limits is tight (0 binding); across the book, 48 binding borrow limits all show a positive dual. `pb_borrow.csv`, `30_constraints.csv` |
| E4 | At least one PM has u_k < 0 (offset or dilution credit) | **Not confirmed** | No PM has u_k < 0; smallest is PM08 at 10,172,525 USD. `attribution.csv` |
| E5 | θ 0.25 → 0.30 lowers M; θ → 0.20 raises M (weakly) | **Confirmed** | M: θ 0.20 1,749,176,390 > base 1,747,690,859 > θ 0.30 1,745,978,305 USD (each scenario re-optimised). `50_sensitivity.csv` |

Split hedged families (E1): CE_ISS004 L2 (PB_A, PB_B, PB_D); CE_ISS006 L2 (PB_A, PB_B, PB_D); CE_ISS009 L3 (PB_A, PB_B, PB_D); CE_ISS013 L2 (PB_A, PB_B); CE_ISS014 L1 (PB_A, PB_B, PB_D); CE_ISS016 L2 (PB_A, PB_B, PB_D); CE_ISS017 L3 (PB_A, PB_B, PB_C, PB_D); CE_ISS018 L1 (PB_A, PB_B, PB_C, PB_D); CE_ISS020 L2 (PB_A, PB_B, PB_C); CE_ISS023 L1 (PB_A, PB_B, PB_D); CE_ISS025 L1 (PB_A, PB_B, PB_C, PB_D); CE_ISS027 L1 (PB_A, PB_B, PB_D); ES_ISS013 L1 (PB_A, PB_C); GB_SOV01 L1 (PB_A, PB_B, PB_C, PB_D); GB_SOV02 L1 (PB_A, PB_B, PB_C).

## 10. What these results are not

Model behaviour under stated assumptions on a synthetic book – not predictions, not calibrated to any prime broker, exchange or clearing house, and not validated. Limitations: [`docs/MODEL_DOC.md`](docs/MODEL_DOC.md) §11; validation status: §12.

