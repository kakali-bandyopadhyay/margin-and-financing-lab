# RESULTS – margin-and-financing-lab, primary run (seed 42)

Run: `python -m mfl.cli run --seed 42` at commit `9b79274` · Python 3.14.7 · DuckDB 2.0.0 · HiGHS 1.16.0 · run timestamp 2026-11-18T16:18:39 UTC.  
Tests at this commit: 81 passed (`python -m pytest -W error -q`); CI green.  
Every number below is copied by script from the run's CSVs in `reports/run_42/` (`results/` and `tables/`); none are typed by hand. The primary run's outputs are committed in [`reports/run_42/`](reports/run_42/) (`run_meta.json`, `report.html`, `results/`, `tables/`); rerunning the command above regenerates them. Model, parameters and expected behaviour were fixed in advance in [`prereg/PREREGISTRATION.md`](prereg/PREREGISTRATION.md); departures are in [`prereg/DEVIATIONS.md`](prereg/DEVIATIONS.md). How to read these numbers, and what they are not, is in [`docs/MODEL_DOC.md`](docs/MODEL_DOC.md). Synthetic data; illustrative charge policy; not validated.

Reproducibility: this run's 26 output CSVs are byte-identical to an earlier run of the same data at commit `c8f0dfd` (the commits in between changed load-time validation in `io.py`, report display in `report.py`, documentation and tests; M1–M3 and exhibit code are unchanged).

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

Ratios printed by `python -m pytest tests/acceptance/test_a7_exchange_sanity.py -s -q` at `9b79274` (1 passed):

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

## 11. Phase 2a – stress projection

Run `python -m mfl stress --seed 42 --data data --out reports/stress_42`; the CSVs are in [`reports/stress_42/`](reports/stress_42/). ST0 reproduces the Phase 1 `run_42` totals to the cent (S1), so the scenario deltas are measured against the same book and optimiser. Amounts are USD. The cost columns cover 90 days: ST0–ST2b start at 2026-10-30; ST3/ST4 start at 2027-03-05 because PB_D's notice is 126 days (see the timing note below).

ST2a and ST2b are **margin-rate shocks**: they multiply the PB margin `base_rate` by 1.5, not the financing spread `financing_spread_bps`. Financing cost therefore moves only through reallocation, and the margin-funding cost moves with the margin base.

### Summary

| Scenario | Total margin | Δ margin | Status | Capacity slack | Counterparty slack | Borrow slack | Additional funding requirement |
|---|---:|---:|---|---:|---:|---:|---:|
| ST0 base | 1,747,690,859.46 | 0.00 | optimal | 0.00 | 0.00 | 0.00 | 0.00 |
| ST1a vol ×2 | 1,903,183,814.12 | 155,492,954.66 | optimal | 0.00 | 0.00 | 0.00 | 155,492,954.66 |
| ST1b vol ×1.5 | 1,888,285,773.40 | 140,594,913.93 | optimal | 0.00 | 0.00 | 0.00 | 140,594,913.93 |
| ST2a margin rate ×1.5, all PBs | 2,589,725,771.13 | 842,034,911.67 | infeasible | 0.00 | 374,692,417.13 | 0.00 | 1,216,727,328.80 |
| ST2b margin rate ×1.5, PB_D + PB_A | 2,266,843,405.64 | 519,152,546.17 | infeasible | 0.00 | 51,810,051.64 | 0.00 | 570,962,597.81 |
| ST3 PB_D termination | 1,794,630,573.66 | 46,939,714.20 | infeasible | 0.00 | 411,509,543.66 | 61,924,557.00 | 520,373,814.86 |
| ST4 combined | 2,226,410,109.27 | 478,719,249.80 | infeasible | 0.00 | 843,289,079.27 | 61,924,557.00 | 1,383,932,886.07 |

| Scenario | Financing cost | Δ financing | Margin-funding cost | Δ margin funding |
|---|---:|---:|---:|---:|
| ST0 base | 17,345,110.09 | 0.00 | 4,369,227.15 | 0.00 |
| ST1a vol ×2 | 17,381,879.30 | 36,769.20 | 4,757,959.54 | 388,732.39 |
| ST1b vol ×1.5 | 17,372,788.76 | 27,678.67 | 4,720,714.43 | 351,487.28 |
| ST2a margin rate ×1.5, all PBs | — | — | — | — |
| ST2b margin rate ×1.5, PB_D + PB_A | — | — | — | — |
| ST3 PB_D termination | — | — | — | — |
| ST4 combined | — | — | — | — |

For an infeasible scenario the margin and slack columns use the minimum-total-slack allocation; financing and margin-funding costs are undefined and shown as “—”. The additional funding requirement is `Δ margin + capacity slack + counterparty slack + borrow slack`, as pre-registered. It is **not a cash amount**: counterparty slack is margin above the counterparty limits, so it is already counted in total margin (in ST3, PB_B's margin rise equals the 411.51m counterparty slack to the cent), and the figure adds a limit shortfall to a margin increase. There is no available-liquidity or buffer term, so it is not a liquidity-coverage gap.

### Expected behaviour E-S1–E-S5

| ID | Expectation (prereg §4) | Result | Evidence |
|---|---|---|---|
| E-S1 | ST1a, ST1b, ST2a, ST2b and ST4 total margin ≥ ST0 | **Met** | All five deltas are positive: +155.49m, +140.59m, +842.03m, +519.15m, +478.72m. |
| E-S2 | ST2a moves few or no positions; ST2b moves positions away from the two shocked PBs | **Not met for ST2a; direction met (net) for ST2b** | ST2a changes 92 of 214 positions, but ST2a is infeasible and those moves come from the relaxed solver solution, so they are not a clean control allocation. ST2b changes 104 positions (154 from→to rows: 56 leave PB_A/PB_D for PB_B/PB_C, 33 move the other way); net allocated notional at PB_D + PB_A falls by 467.28m versus ST0. |
| E-S3 | In ST3 no position remains at the terminated PB | **Met** | PB_D is removed from the feasible set; `max_i w_ST3(i, PB_D) = 0`, and the written ST3 PB_D row has zero margin, gross and utilisation. |
| E-S4 | ST3 total margin rises by more than reallocation alone explains, because offsets within the terminated PB are lost | **Not met** | ST3 total margin rises 46.94m, but reallocation alone is +70.39m and total netting change is −23.45m: netting benefit rose on reallocation rather than falling. PB_D's own 79.49m netting benefit is lost, but the receiving PBs gain more. See `stress_st3_netting.csv`. ST3 is infeasible: the whole 411.51m counterparty shortfall sits at PB_B, so this decomposition describes the minimum-slack allocation, not an optimised post-termination book. |
| E-S5 | ST4 additional funding requirement ≥ the largest of ST1a, ST2b and ST3 | **Met** | ST4 1,383.93m ≥ max(155.49m, 570.96m, 520.37m) = 570.96m. |

### Findings and qualifications

- **PB_D stays live for the whole 90-day horizon under its own notice terms.** `notice_days = 126` is longer than the 90-day horizon. The pre-registration fixes the consequence in §3.6: ST3/ST4 are evaluated at the termination date 2027-03-05, and their 90-day cost window starts there. This is a fixed timing convention, not a second horizon; it means ST3/ST4 are not cash-flow comparisons over the same calendar window as ST0–ST2b. The finding for a reader is that PB_D's notice period alone outlasts the horizon.
- **ST2a's infeasibility matters for interpretation.** The uniform margin-rate shock breaches the counterparty limits by 374.69m; its 92 changed positions are from the relaxed solution. Treat ST2a as a control that shows how far a uniform margin-rate shock moves the margin base, not as a clean reallocation experiment.
- **ST2b does move away from the shocked PBs.** PB_D + PB_A allocated notional falls by 467.28m, with a 51.81m counterparty shortfall. The move is a direction, not a claim that the post-shock book is feasible.
- **ST3/ST4 termination.** Both remove PB_D and report the same 2,912,025,250.53 notional to move across 106 ST0 positions (ST4 uses the same fixed ST0 basis; D-11). The ST3/ST4 borrow slack is 61.92m, from the two ISS010 shorts (`POS0076`, `POS0098`) that had a locate only at PB_D; the remainder of the slack is counterparty. No position remains at PB_D.
- **The netting decomposition is reported separately from reallocation.** `stress_st3_netting.csv` shows `margin_with_offsets`, `margin_without_offsets`, the ST0 netting benefit and `netting_change = NB(ST0) − NB(ST3)`; the identity `Δ margin = reallocation + netting_change` holds row by row and in total. The negative total netting change is why E-S4 is not met.
- **Rounding.** Stress CSVs are rounded to 7 decimal places in the stress writer only; `io.write_csv` and the Phase 1 outputs are unchanged. This removes values such as `29.100000000000001` without altering the S6 identity.

This projection is illustrative, not calibrated and not any firm's methodology. Cleared or exchange margin, path dependence and margin-call dynamics are out of scope.

## 12 Phase 2b – calibration

These are the Phase 2b outputs, reported as found. The exercise uses illustrative public-market proxies and assumed margin periods of risk; it is not validated and is not a claim about any broker or regulatory methodology. Results below are transcribed from the `reports/calib_42` CSVs.

### Input reproduction

| Symbol | Source | Field | First date | Last date | Rows | Digest comparison |
| --- | --- | --- | --- | --- | --- | --- |
| DEXUSEU | FRED | DEXUSEU | 2015-01-02 | 2026-10-30 | 2,957 | identical |
| DGS10 | FRED | DGS10 | 2015-01-02 | 2026-10-30 | 2,959 | identical |
| GLD | Tiingo | adjClose | 2015-01-02 | 2026-10-30 | 2,975 | identical |
| HYG | Tiingo | adjClose | 2015-01-02 | 2026-10-30 | 2,975 | identical |
| SPY | Tiingo | adjClose | 2015-01-02 | 2026-10-30 | 2,975 | identical |

All five local raw files have SHA-256 digests identical to the committed input digest. Reproduction status (§1.4): reproduced byte-identical on a clean clone, 23 Nov 2026 (commit 0e2a37e): all five raw-input digests identical; every reports/calib_42 file identical after re-running the calibrate CLI.

### Calibration targets

| Product type | proxy | h | n_recent | ES_recent_long | ES_recent_short | ES_recent | ES_stress | stress_window_end | floor_binding | T | b_t | R_t | k_t |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cash_equity | SPY | 10 | 501 | 0.078283 | 0.073283 | 0.078283 | 0.222669 | 2020-03-23 | No | 0.114380 | V2 | 0.174497 | 0.504218 |
| cds_proxy | HYG | 5 | 501 | 0.017473 | 0.015785 | 0.017473 | 0.096872 | 2020-03-23 | No | 0.037323 | V1 | 0.066208 | 0.563725 |
| commodity_future | GLD | 2 | 501 | 0.065027 | 0.050934 | 0.065027 | 0.083053 | 2026-06-10 | No | 0.069534 | V3 | 0.088806 | 0.434989 |
| equity_swap | SPY | 10 | 501 | 0.078283 | 0.073283 | 0.078283 | 0.222669 | 2020-03-23 | No | 0.114380 | V2 | 0.153582 | 0.572883 |
| fx_forward | DEXUSEU | 10 | 500 | 0.027483 | 0.043681 | 0.043681 | 0.057416 | 2016-01-14 | No | 0.047115 | V1 | 0.034125 | 1.380636 |
| govt_bond | DGS10 | 10 | 499 | 0.028551 | 0.022589 | 0.028551 | 0.050620 | 2020-04-01 | No | 0.034068 | V1 | 0.021051 | 1.618377 |
| irs_proxy_future | DGS10 | 2 | 499 | 0.013452 | 0.012336 | 0.013452 | 0.022585 | 2023-02-06 | No | 0.015735 | V1 | 0.034947 | 0.450254 |

### Walk-forward backtest

The table retains both sides and APC/no-APC results. `Worse side` is derived from the higher recorded exceedance rate within each product type and APC setting; ties are both marked. Kupiec POF and traffic-light zones use the registered 1% nominal rate.

| Product type | Side | APC | Windows | Exceedances | Rate | Kupiec LR | Kupiec p | Zone | Worse side |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cash_equity | long | No | 175 | 2 | 0.011429 | 0.034486 | 0.852676 | green | Yes |
| cash_equity | long | Yes | 175 | 1 | 0.005714 | 0.384011 | 0.535465 | green | Yes |
| cash_equity | short | No | 175 | 0 | 0 | 3.517618 | 0.060720 | green | No |
| cash_equity | short | Yes | 175 | 0 | 0 | 3.517618 | 0.060720 | green | No |
| cds_proxy | long | No | 361 | 5 | 0.013850 | 0.482715 | 0.487195 | green | Yes |
| cds_proxy | long | Yes | 361 | 3 | 0.008310 | 0.110468 | 0.739612 | green | Yes |
| cds_proxy | short | No | 361 | 2 | 0.005540 | 0.865000 | 0.352343 | green | No |
| cds_proxy | short | Yes | 361 | 2 | 0.005540 | 0.865000 | 0.352343 | green | No |
| commodity_future | long | No | 949 | 14 | 0.014752 | 1.888608 | 0.169359 | green | Yes |
| commodity_future | long | Yes | 949 | 9 | 0.009484 | 0.026003 | 0.871893 | green | No |
| commodity_future | short | No | 949 | 14 | 0.014752 | 1.888608 | 0.169359 | green | Yes |
| commodity_future | short | Yes | 949 | 10 | 0.010537 | 0.027207 | 0.868988 | green | Yes |
| equity_swap | long | No | 175 | 2 | 0.011429 | 0.034486 | 0.852676 | green | Yes |
| equity_swap | long | Yes | 175 | 1 | 0.005714 | 0.384011 | 0.535465 | green | Yes |
| equity_swap | short | No | 175 | 0 | 0 | 3.517618 | 0.060720 | green | No |
| equity_swap | short | Yes | 175 | 0 | 0 | 3.517618 | 0.060720 | green | No |
| fx_forward | long | No | 173 | 1 | 0.005780 | 0.366864 | 0.544719 | green | No |
| fx_forward | long | Yes | 173 | 0 | 0 | 3.477416 | 0.062212 | green | No |
| fx_forward | short | No | 173 | 3 | 0.017341 | 0.772386 | 0.379480 | green | Yes |
| fx_forward | short | Yes | 173 | 3 | 0.017341 | 0.772386 | 0.379480 | green | Yes |
| govt_bond | long | No | 173 | 2 | 0.011561 | 0.040529 | 0.840450 | green | Yes |
| govt_bond | long | Yes | 173 | 2 | 0.011561 | 0.040529 | 0.840450 | green | Yes |
| govt_bond | short | No | 173 | 2 | 0.011561 | 0.040529 | 0.840450 | green | Yes |
| govt_bond | short | Yes | 173 | 1 | 0.005780 | 0.366864 | 0.544719 | green | No |
| irs_proxy_future | long | No | 946 | 7 | 0.007400 | 0.710185 | 0.399382 | green | No |
| irs_proxy_future | long | Yes | 946 | 7 | 0.007400 | 0.710185 | 0.399382 | green | No |
| irs_proxy_future | short | No | 946 | 12 | 0.012685 | 0.634917 | 0.425557 | green | Yes |
| irs_proxy_future | short | Yes | 946 | 9 | 0.009514 | 0.022965 | 0.879547 | green | Yes |

With 173–175 non-overlapping windows for h = 10, zero exceedances gives Kupiec p ≈ 0.06: at these sample sizes the test has little power to reject a conservative target, and every zone is green.

### Exchange-margin drivers

| Driver | Setting | ES recent | T | PB | Pre-buffer unit margin | ZN initial margin / notional (decimal) | Ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| confidence | ES 97.5 (base) | 0.013452 | 0.015735 |  |  |  |  |
| confidence | VaR 99 | 0.013124 | 0.015603 |  |  |  |  |
| confidence | ES 99 | 0.016259 | 0.019136 |  |  |  |  |
| MPOR | 1 trading days | 0.009988 | 0.011630 |  |  |  |  |
| MPOR | 2 trading days (base) | 0.013452 | 0.015735 |  |  |  |  |
| MPOR | 5 trading days | 0.022044 | 0.024901 |  |  |  |  |
| lookback | 1 years | 0.012325 | 0.014890 |  |  |  |  |
| lookback | 2 years (base) | 0.013452 | 0.015735 |  |  |  |  |
| lookback | 5 years | 0.018284 | 0.019359 |  |  |  |  |
| APC | none | 0.013452 | 0.013452 |  |  |  |  |
| APC | 25% stressed weight with floor | 0.013452 | 0.015735 |  |  |  |  |
| APC | 25% buffer | 0.013452 | 0.016815 |  |  |  |  |
| APC | 10-year lookback floor | 0.013452 | 0.016760 |  |  |  |  |
| scaling | overlapping h=2 (base) | 0.013452 | 0.015735 |  |  |  |  |
| scaling | sqrt(2) × 1-day | 0.014125 | 0.016447 |  |  |  |  |
| ZN comparison | PB_A at Phase 1 bucket V1 |  |  | PB_A | 0.016630 | 0.017754 | 0.936667 |
| ZN comparison | PB_B at Phase 1 bucket V1 |  |  | PB_B | 0.019049 | 0.017754 | 1.072955 |
| ZN comparison | PB_C at Phase 1 bucket V1 |  |  | PB_C | 0.011752 | 0.017754 | 0.661936 |
| ZN comparison | PB_D at Phase 1 bucket V1 |  |  | PB_D | 0.014790 | 0.017754 | 0.833044 |

### Pre-registered expectations

| ID | Result | Evidence |
| --- | --- | --- |
| E-C1 | Met | Stressed ES exceeds recent ES on every target row, so the floor is non-binding. |
| E-C2 | Met | MPOR target is increasing; ES 97.5 is at least VaR 99; the ES-recent and target scaling gaps are 5.00% and 4.52%, respectively. |
| E-C3 | Met | APC strictly lowers the worse-side count for 5 of the seven product types. cash_equity and equity_swap share SPY and h = 10, so their backtest rows are identical by construction; counted on distinct proxy/h pairs the result is 4 of 6. |
| E-C4 | Not met | No PM rank changes in the calibrated charge output. |
| E-C5 | Met | All four ZN ratios are inside the registered 0.5–3 range; observed range 0.662–1.073. |

Formula-implied properties (including APC not below no-APC) are acceptance-test results, not empirical expectations. E-C1–E-C5 are reported as found; no parameters were retuned to meet them.

### Re-optimised calibrated case

| status | total margin usd | delta total margin usd | financing cost usd | delta financing cost usd | margin funding cost usd | delta margin funding cost usd | slack capacity usd | slack counterparty usd | slack borrow usd | total slack usd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| optimal | $944,334,264.71 | -$803,356,594.75 | $16,896,602.15 | -$448,507.95 | $2,360,835.66 | -$2,008,391.49 | 0 | 0 | 0 | 0 |

The −$803.36m is a change in the level of total margin, not a cost saving or a cash amount. Five of the seven types have k_t below 1 (0.43–0.57) because the synthetic Phase 1 rates sit above the proxy-implied targets; fx_forward and govt_bond are scaled up (1.38 and 1.62). The financing and margin-funding deltas are illustrative consequences of the same rescaling.

### PM charge changes

Top ten rows ranked by absolute charge change in `calib_pm_charges.csv`; the complete table remains in that CSV.

| PM | Phase 1 charge | Calibrated charge | Change | Phase 1 rank | Calibrated rank | Rank change |
| --- | --- | --- | --- | --- | --- | --- |
| PM05 | $1,528,403.74 | $854,912.75 | -$673,490.99 | 1 | 1 | 0 |
| PM01 | $1,043,390.62 | $526,339.01 | -$517,051.62 | 2 | 2 | 0 |
| PM03 | $466,004.18 | $250,620.19 | -$215,383.99 | 3 | 3 | 0 |
| PM04 | $331,544.78 | $171,964.16 | -$159,580.62 | 5 | 5 | 0 |
| PM06 | $296,064.20 | $147,693.50 | -$148,370.70 | 6 | 6 | 0 |
| PM02 | $357,324.63 | $210,520.89 | -$146,803.74 | 4 | 4 | 0 |
| PM09 | $148,845.42 | $88,192.95 | -$60,652.47 | 7 | 7 | 0 |
| PM07 | $90,434.06 | $46,690.84 | -$43,743.22 | 8 | 8 | 0 |
| PM10 | $77,989.75 | $36,353.42 | -$41,636.33 | 9 | 9 | 0 |
| PM08 | $29,225.76 | $27,547.94 | -$1,677.82 | 10 | 10 | 0 |

The calibrated allocation status and slacks are shown in the summary table. PM charge changes are illustrative pass-through amounts under the stated policy. None of these results establishes model validity.
