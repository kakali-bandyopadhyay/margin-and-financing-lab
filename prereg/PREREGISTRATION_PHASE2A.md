# Pre-registration – Phase 2a: liquidity stress add-on

**Status:** Final for Phase 2a, created 22 Nov 2026 from spec v1.1 (22 Nov 2026; supersedes v1 of 20 Nov). Committed as a separate commit before `src/mfl/stress.py` or `tests/acceptance/test_stress.py` exists; the commit is tagged `v0.2-prereg-stress`. Once committed, any change to the scenarios, transforms, parameters, output definitions or tests is logged in `prereg/DEVIATIONS.md` with date, reason and effect.

**Baseline:** `margin-and-financing-lab` at HEAD `15b5867`; Phase 1 is untouched. The primary case is seed 42, `as_of_date` 2026-10-30, 90-day horizon; the reference outputs are `reports/run_42/`. There is no change to M1–M3, `run_42` outputs or A1–A7.

**Authorship (repo rule – `S1_GUIDE.md` and spec §1):** the pre-registration, `src/mfl/stress.py` (scenario transforms + additional-funding-requirement calculation) and the S1–S7 acceptance tests + hand-worked checks are the author's. The AI assistant does plumbing only: CLI subcommand, report section, CSV writers, plumbing tests, CI, and README/RESULTS/MODEL_DOC drafts. The AI assistant must NOT write `stress.py` logic or S1–S7. If a plumbing step needs a function that does not exist yet, it stubs it with `NotImplementedError` and stops.

**Relationship to v1 (recorded for the record):** v1.1 splits ST2 into a uniform control (ST2a) and an asymmetric shock (ST2b); rewrites S3 because the concentration add-on uses `conc_rate`, not `base_rate`; recasts ST3 as a NAV-trigger termination using `notice_days`; adds ST1b for bucket coarseness; renames "funding gap" to "additional funding requirement"; and states the cleared/exchange-margin scope-out. This document implements those changes.

## 1. Purpose, scope and boundary

### 1.1 Purpose

A small, pre-registered **static** stress projection of the Phase 1 book: how much additional margin/funding the book needs under a named stress, and where the allocation moves. It covers part of the stress-liquidity duty – prime-broker margin and funding stress, and the legal-agreement terms already in the data (`notice_days`, `nav_trigger_pct`).

### 1.2 In scope

- The Phase 1 prime-broker margin proxy and financing only.
- Volatility re-bucketing, base-rate shocks, one PB termination, and their fixed combination.
- The legal terms `notice_days` and `nav_trigger_pct` as specified in §3.6, reported as found.
- The fixed scenario transforms, PB choices, output schemas and acceptance tests below.

### 1.3 Out of scope (fixed)

- Cleared and exchange margin; trading-pattern modelling; path dependence; margin-call dynamics.
- Any available-liquidity, cash-buffer or liquidity-coverage calculation. The "additional funding requirement" is defined in §4.7 and is **not** a liquidity-coverage gap.
- Calibration to any provider or firm; any firm's methodology; any forecast. The stress is illustrative and static.
- Fixed-horizon statistical factor forecasting (covered separately by `vol-forecast-lab`).
- Changes to Phase 1, new synthetic inputs, or new parameters.

### 1.4 Scope paragraph (spec §6, verbatim; the author may edit wording only)

> "Phase 2a stresses the prime-broker margin proxy and financing only. Cleared and exchange margin are out of scope: they are set by exchange and clearing-house models (e.g. SPAN-style scenario margin and clearing-house rules), not by PB rate schedules, and Phase 1 uses exchange initial margin only as a scale sanity check (A7). Trading-pattern effects, intraday or path-dependent margin and margin-call dynamics are also out of scope. The stress is static over the 90-day horizon."

## 2. Baseline, notation and conventions

### 2.1 Phase 1 primary case (unchanged)

| Item | Value |
|---|---|
| Seed | 42 |
| `as_of_date` | 2026-10-30 |
| Horizon `H` | 90 days |
| `liquidity_premium_bps` | 100 |
| `house_buffer` | 1.15 |
| `phi` | 0.60 |
| `conc_threshold` | 0.25 |
| `conc_rate` | 0.02 |
| Vol cuts | 0.10 / 0.20 |
| Vol multipliers | V1 1.0, V2 1.3, V3 1.8 |
| Data | `data/raw/*` only; no new synthetic inputs |

The book, rates, providers, borrow, prices and parameters are exactly those loaded by `mfl.io.load_case`. `run_42` is the Phase 1 output under these inputs.

### 2.2 Margin operator (Phase 1 notation, unchanged)

For allocation matrix `w` (position × PB), position notional `N_i`, side `s_i`:

```
gross(f,p) = sum_{i in f} N_i * w(i,p)
net(f,p)   = |sum_{i in f} s_i * N_i * w(i,p)|
r(f,p)     = base_rate(p, product, tier) * vol_mult(vol_bucket)
FM(f,p)    = r(f,p) * (phi * net(f,p) + (1 - phi) * gross(f,p))
G(g,p)     = sum_{i in issuer g} N_i * w(i,p)
G(p)       = sum_i N_i * w(i,p)
addon(g,p) = conc_rate(p) * max(0, G(g,p) - conc_threshold(p) * G(p))
M(p)       = house_buffer * (sum_f FM(f,p) + sum_g addon(g,p))
M          = sum_p M(p)
```

`f = (product, liquidity_tier, vol_bucket)`. Netting is within a family and within a PB only; there is no cross-PB netting. Reported margin is always recomputed from the allocation by `margin.py`, never read from solver epigraph variables.

### 2.3 Allocation, status and slack

- Each scenario is solved with `mfl.optimise.optimise(book, rates, providers, borrow, params)`; objective, constraints, HiGHS settings and `ell_bps = 100` are unchanged.
- `w0` is the ST0 allocation; `M0 = M(w0)`.
- `w_s` and `M_s = M(w_s)` are the scenario allocation and total margin.
- If `status == "optimal"`, costs and slacks are defined. If `"infeasible"`, `w_s` is the minimum-total-slack allocation returned by the Phase 1 slack re-solve, costs are NaN, and slacks are reported. Any other solver status fails the run; it is not reported as a scenario.
- **Slack amounts are recomputed from the returned allocation and the Phase 1 margin model**, not read from solver epigraph variables. For each block:

```
capacity_slack(p)     = max(0, G(p) - capacity_usd(p))
counterparty_slack(p) = max(0, M(p) - counterparty_limit_usd(p))
borrow_slack(p,g)     = max(0, sum_{short i in g, needs_locate} N_i * w(i,p)
                                - borrow_available_usd(p,g))
total_slack           = sum_p capacity_slack(p)
                      + sum_p counterparty_slack(p)
                      + sum_{p,g} borrow_slack(p,g)
```

This keeps the reported margin and the reported slack on the same basis and avoids changing Phase 1. For an optimal status every recomputed slack must be at most `1e-6` USD; otherwise the run fails. For an infeasible status at least one slack is `> 1e-6` USD.

### 2.4 Determinism, tolerances and ordering

- A weight is zero for reporting when `w <= 1e-9`.
- USD comparisons use `1e-6` unless a test says otherwise; S1 uses cents.
- PB order is `providers.csv` order: `PB_A, PB_B, PB_C, PB_D`.
- Scenario order is fixed: `ST0, ST1a, ST1b, ST2a, ST2b, ST3, ST4`. This is the CSV row order and the report order; scenarios are not sorted alphabetically.
- Ties in PB selection are broken by provider order.
- Every reported number comes from the CSVs; RESULTS.md does not hand-copy numbers.

## 3. Scenarios (fixed before any code)

All scenarios start from the Phase 1 primary case. Only the inputs listed for each scenario change. `params`, `book` notionals/sides/issuers, and the house buffer are otherwise unchanged. Every scenario is re-optimised independently from the transformed inputs; no scenario inherits another scenario's allocation.

| ID | Name | Transform | Role |
|---|---|---|---|
| ST0 | base | Phase 1 case unchanged | must reproduce `run_42` exactly |
| ST1a | vol_x2 | Annualised realised vol per product (same window/rule as `margin.vol_bucket`) × 2, re-bucketed with the unchanged cuts 0.10 / 0.20 | vol shock |
| ST1b | vol_x1.5 | As ST1a with × 1.5 | shows how coarse the three-bucket mapping is |
| ST2a | rates_uniform_x1.5 | Every PB's `base_rate` × 1.5 | **control**: shows how far a uniform shock moves the allocation (only via the unscaled financing-spread term, the unscaled concentration add-on and binding limits) |
| ST2b | rates_top2_x1.5 | `base_rate` × 1.5 for the two PBs with the largest Phase 1 allocated margin only | differentiated funding pressure → reallocation |
| ST3 | pb_termination | The PB with the largest Phase 1 allocated margin breaches its `nav_trigger_pct` and terminates: capacity → 0 after its `notice_days`; all its positions must be re-placed at the remaining PBs; report `notice_days` and the notional to move | legal-agreement terms + loss of within-PB netting |
| ST4 | combined | ST1a + ST2b + ST3 | combined stress |

### 3.1 ST0 – base

No input change. Solve the Phase 1 case and use `w0`. ST0 is the control and the reproducibility check for S1; it is not a stress. If ST0 is not `optimal`, the stress run fails.

### 3.2 ST1a – vol_x2

1. For each held product, take `price_history` closes with date ≤ `as_of_date`, sorted ascending.
2. Compute the last 60 close-to-close log returns; `sigma_p = sample_std(ddof=1) * sqrt(252)`. This is exactly the Phase 1 `margin.vol_bucket` window/rule.
3. Stressed vol `sigma'_p = 2.0 * sigma_p`.
4. Re-bucket with the unchanged cuts:
   - `sigma' < 0.10` → V1
   - `0.10 <= sigma' <= 0.20` → V2
   - `sigma' > 0.20` → V3
5. Set `book["vol_bucket"]` for every position of product `p` to the stressed bucket. Nothing else changes: rates, providers, borrow, notionals, sides, tiers and the vol multipliers (1.0 / 1.3 / 1.8) are unchanged.
6. Re-optimise. The new buckets change family keys and family margin; they do not change the vol multipliers.

A product with fewer than 60 usable returns has no stressed vol estimate; it remains V3, matching the Phase 1 conservative default. Products at exactly 0.10 or 0.20 are V2 (the Phase 1 inclusive cut rule).

### 3.3 ST1b – vol_x1.5

Exactly as ST1a with `sigma'_p = 1.5 * sigma_p` and the same cuts. Role: show how coarse the three-bucket mapping is; it is not a second shock family and is not used in ST4.

### 3.4 ST2a – rates_uniform_x1.5

1. For every row of `pb_rates`, set `base_rate <- 1.5 * base_rate`.
2. `financing_spread_bps` and `phi` are unchanged.
3. Re-optimise.

At the fixed ST0 allocation, every family's `r` scales by 1.5, so `family_margin` scales by 1.5 at every PB. The concentration add-on does **not** scale: it uses `conc_rate`, not `base_rate`. Total margin therefore does not scale exactly by 1.5: `M = 1.15 * (1.5 * FM0 + addon0)`. S3 checks this. Financing cost at fixed allocation is unchanged because it uses `financing_spread_bps` only; the allocation can still move because the margin-funding term is scaled relative to the unscaled financing term.

### 3.5 ST2b – rates_top2_x1.5

1. Rank PBs by their ST0 allocated margin `M0(p)`, descending; ties by provider order. For the primary case the top two are **PB_D** (`764,910,552.84`) and **PB_A** (`477,120,106.14`). The rule, not the names, is normative; the names are fixed data facts in §7.
2. For `pb_rates` rows whose `pb_id` is in that top-two set, set `base_rate <- 1.5 * base_rate`. All other PBs' `base_rate` is unchanged.
3. `financing_spread_bps` and `phi` are unchanged everywhere.
4. Re-optimise.

At the fixed ST0 allocation, family margin at the two shocked PBs is 1.5 × ST0 and unchanged at the other PBs; the concentration add-on is unchanged everywhere because `conc_rate` and gross exposures are unchanged. S4 checks this. The top two are selected from ST0 and are **not** re-selected after the shock or after a termination.

### 3.6 ST3 – pb_termination

**Terminated PB.** The PB with the largest ST0 allocated margin. For the primary case that is **PB_D** (`notice_days = 126`, `nav_trigger_pct = 29.1`, `capacity_usd = 3,948,127,000`). The rule is normative; the names are fixed data facts in §7.

**Event.** The fund is assumed to be below PB_D's `nav_trigger_pct` at the termination date. Phase 1 has no NAV series and 2a does not simulate one: the breach is an assumed event, not a tested one. The trigger value is reported; no NAV path, cure period or negotiation is modelled.

**Notice and timing.** `notice_days(PB_D) = 126`, which is greater than `H = 90`. To apply "capacity → 0 after its `notice_days`" without pretending the exit happens on day 0, ST3 is evaluated at

```
T3 = as_of_date + notice_days(PB_D) = 2026-10-30 + 126 days = 2027-03-05.
```

The book and all market inputs are static: the same Phase 1 data are used at `T3`, with no market move, no new prices and no path. Margin is a stock and is unaffected by the date. The 90-day financing / margin-funding cost window starts at `T3`; the horizon length is still exactly 90 days. `cost_window_start` in `stress_summary.csv` records this. This timing convention is fixed here; it is not a second horizon and does not change `H`. ST4 uses the same `T3` because it terminates the same PB.

**Re-placement.** Remove PB_D from the feasible set: the stress solve uses `providers`, `pb_rates` and `pb_borrow` without PB_D. Every position must be allocated to one of `PB_A`, `PB_B`, `PB_C`. This construction guarantees zero allocation to PB_D even in an infeasible slack solution; a position is never left at the terminated PB. Internally the ST3/ST4 solve has three PB columns; for every output, test and the §4.4 decomposition, the allocation is placed on the full four-PB grid with `w3(i, PB_D) = 0`.

**Locate relaxation (fixed).** Two short positions need a locate that is available only at PB_D (`POS0076`, `POS0098`, issuer `ISS010`). Removing PB_D must not become an input error or silently drop them. For ST3 and ST4 only:

- Every remaining PB is an allowed venue for a `needs_locate` short;
- `borrow_fee_bps` for that PB/issuer is used in the objective even where `borrow_available_usd = 0` (the fee row exists at every PB for every held locate issuer in the primary data);
- the availability shortfall is carried by `borrow_slack` in the standard slack re-solve.

This makes the missing locate a **reported borrow gap** rather than an input error. The first (no-slack) solve still enforces `available = 0` and is therefore infeasible for the primary case (both positions need PB_D); the slack re-solve returns the allocation and the gap. If a future data set has no borrow row at any remaining PB, the position is still reported as a borrow gap with a zero fee; the scenario is infeasible and the gap is in `slack_borrow_usd`.

**Notional to move.** Report the allocated notional at PB_D in ST0:

```
notional_to_move_usd = sum_i N_i * w0(i, PB_D)  (primary case: 2,912,025,250.53)
positions_moved      = count_i [w0(i, PB_D) > 1e-9]  (primary case: 106)
```

This is the amount that must be re-placed, not the full notional of every position that touches PB_D. The per-position routing is in `stress_moves.csv`.

**Status.** ST3 may be optimal or infeasible. If infeasible, status is `"infeasible"`, `total_slack_usd > 0`, and the allocation is the minimum-total-slack solution on the remaining PBs. The margin decomposition in §4.4 is computed on that returned allocation. S5 accepts either status, provided the allocation to PB_D is zero and, if infeasible, slack is positive.

### 3.7 ST4 – combined

Apply, in the same solve:

1. ST1a vol re-bucketing (× 2);
2. ST2b base-rate shocks at the ST0 top two PBs (`PB_D`, `PB_A`);
3. ST3 termination of `PB_D` at `T3`, with the same locate relaxation and the same `cost_window_start`.

The order of applying these transforms does not matter for the resulting inputs. Because `PB_D` is removed, its ST2b rate shock has no effect on the re-placed book; `PB_A`'s shock does. The top two are still the ST0 top two, not re-selected after termination. There is no interaction term and no new calibration. ST4's pre-termination allocation is not a separate reported scenario, so its `notional_to_move_usd` is left blank; its moves are itemised in `stress_moves.csv`.

### 3.8 Bucket coarseness and the one-line sensitivity

Three buckets with cuts 0.10 / 0.20 make the vol shock coarse: a product moves at most two notches and many products saturate at V3. With the Phase 1 book (73 held products), ST1a moves 27 products (9 V1→V2 and 18 V2→V3) and leaves 42 at V3; ST1b moves 22. These are input-transformation counts, not stress results.

The one-line sensitivity is fixed as follows:

- Take the ST1a stressed vols (`2 * sigma_p`), re-bucket with cuts **0.12 / 0.24**, and re-optimise with otherwise ST1a inputs.
- Report total margin, Δ vs ST0, status and the cuts in `stress_bucket_sensitivity.csv` (one row) and as one line in the report.
- It is **reported, not used**: it is not a scenario, is not in `stress_summary.csv`, and is not used in S1–S7 or E-S1–E-S5.

### 3.9 Fixed choices and interpretations

| Choice | Fixed value |
|---|---|
| ST1a multiplier | 2.0 |
| ST1b multiplier | 1.5 |
| Vol cuts | 0.10 / 0.20; V2 inclusive at both |
| Sensitivity cuts | 0.12 / 0.24, ST1a only |
| ST2a | all PBs, `base_rate` × 1.5 |
| ST2b | ST0 top two PBs = PB_D, PB_A; `base_rate` × 1.5 only there |
| ST3 terminated PB | PB_D (largest ST0 allocated margin) |
| ST3 notice / NAV trigger | 126 days / 29.1% |
| ST3 termination date | 2027-03-05 (as_of + 126 days) |
| ST3 timing | cost window starts at T3; 90-day length unchanged |
| ST3 locate relaxation | remaining PBs allowed; availability shortfall = borrow slack |
| ST4 | ST1a + ST2b + ST3, same T3 |
| Weight zero | 1e-9 |
| USD tolerance | 1e-6 (S1: cents) |
| PB tie-break | provider order |

These are fixed before code. A change is a deviation in `prereg/DEVIATIONS.md`, not an edit to this document after the commit.

## 4. Outputs

All files are written to `reports/stress_42/` by the stress command. Each file is UTF-8 CSV with a header. Scenario rows follow the fixed order in §2.4; do not sort scenarios alphabetically.

### 4.1 `stress_summary.csv`

Exactly 7 rows, one per scenario, in scenario order. Columns:

| Column | Definition |
|---|---|
| `scenario` | ST0, ST1a, ST1b, ST2a, ST2b, ST3, ST4 |
| `cost_window_start` | ISO date: 2026-10-30 for ST0/ST1a/ST1b/ST2a/ST2b; 2027-03-05 for ST3/ST4 |
| `total_margin_usd` | `M_s`; recomputed from `w_s` by `margin.py` |
| `delta_margin_usd` | `M_s - M0` |
| `financing_cost_usd` | scenario financing cost over the 90-day cost window; NaN if infeasible |
| `delta_financing_cost_usd` | scenario minus ST0; NaN if either is NaN |
| `margin_funding_cost_usd` | `total_margin_usd * ell_bps * 1e-4 * H / 360`; NaN if infeasible |
| `delta_margin_funding_cost_usd` | scenario minus ST0; NaN if either is NaN |
| `status` | optimiser status: `optimal` or `infeasible` |
| `slack_capacity_usd` | sum of capacity slacks, §2.3 |
| `slack_counterparty_usd` | sum of counterparty slacks, §2.3 |
| `slack_borrow_usd` | sum of borrow slacks, §2.3 |
| `total_slack_usd` | sum of the three slack columns |
| `additional_funding_requirement_usd` | `delta_margin_usd + total_slack_usd` |
| `terminated_pb` | PB_D for ST3 and ST4; blank otherwise |
| `notice_days` | 126 for ST3 and ST4; blank otherwise |
| `nav_trigger_pct` | 29.1 for ST3 and ST4; blank otherwise |
| `notional_to_move_usd` | ST3 only: `sum_i N_i * w0(i, PB_D)`; blank for ST4 and other scenarios |

If a scenario is infeasible, the three cost columns and their deltas are NaN; the margin, slack and additional-funding-requirement columns are populated from the slack solution. The status and slack columns are never NaN.

The five extra columns (`cost_window_start`, `terminated_pb`, `notice_days`, `nav_trigger_pct`, `notional_to_move_usd`) carry the ST3 legal terms and the timing convention required by §2 and §3.6; they do not add a scenario or change the seven-row rule.

### 4.2 `stress_margin_by_pb.csv`

One row per scenario × PB, 7 × 4 = 28 rows, scenario order then provider order. Columns:

| Column | Definition |
|---|---|
| `scenario` | as above |
| `pb_id` | PB_A, PB_B, PB_C, PB_D |
| `margin_usd` | `M_s(p)` from `margin.py` |
| `gross_usd` | `G(p) = sum_i N_i * w_s(i,p)` |
| `capacity_usd` | capacity used in the scenario; 0 for the terminated PB in ST3/ST4 |
| `utilisation_pct` | `100 * gross_usd / capacity_usd`; 0 when both are zero; NaN if capacity is 0 and gross is positive |

For an infeasible scenario the values are from the slack solution; utilisation may exceed 100% where capacity or counterparty slack was needed. That is reported as found, not clipped.

### 4.3 `stress_moves.csv`

One row per non-zero position-level reallocation versus ST0, across all scenarios. Columns:

| Column | Definition |
|---|---|
| `scenario` | as above |
| `pos_id` | position identifier |
| `from_pb` | PB losing allocated notional |
| `to_pb` | PB gaining allocated notional |
| `notional_moved_usd` | USD allocated notional moved from `from_pb` to `to_pb` |

Because Phase 1 positions can be split across several PBs (49 of 214 at ST0), a move is defined at the allocation level, not only by a change of primary PB. For each position `i`:

```
out(i,p) = N_i * max(0, w0(i,p) - w_s(i,p))
in(i,p)  = N_i * max(0, w_s(i,p) - w0(i,p))
```

Outflows and inflows are matched greedily: iterate `from_pb` in provider order, and for each `from_pb` iterate `to_pb` in provider order; move `min(out, in)` and emit a row when the moved amount is at least `1e-6` USD. This is a canonical routing for reporting, not an actual trade route; per position, the total moved equals `N_i * 0.5 * sum_p |w_s(i,p) - w0(i,p)|`. Differences at or below the weight zero tolerance (1e-9) are ignored. Rows are ordered by scenario order, `pos_id`, `from_pb`, `to_pb`. ST0 has zero rows; the file still has its header.

### 4.4 `stress_st3_netting.csv` – exact ST3 netting method

This file decomposes ST3 margin into (a) the re-placed book computed **position by position with no offsets** at the receiving PBs and (b) the same book **with the Phase 1 within-PB offsets**, so the netting effect is shown separately from reallocation. It is computed for ST3 only. It uses the ST3 allocation `w3` (the slack solution if ST3 is infeasible) and the ST0 allocation `w0`.

#### Definitions

Let `t = PB_D` and `R = {PB_A, PB_B, PB_C}`. For any allocation `w` and PB `p`:

```
gross(f,p;w) = sum_{i in f} N_i * w(i,p)
net(f,p;w)   = |sum_{i in f} s_i * N_i * w(i,p)|
FM(f,p;w)    = r(f,p) * (phi * net(f,p;w) + (1 - phi) * gross(f,p;w))
A(p;w)       = sum_g conc_rate(p) * max(0, G(g,p;w) - conc_threshold(p) * G(p;w))
```

**With offsets (b).** The Phase 1 margin on the re-placed book:

```
M_with(p) = house_buffer * (sum_f FM(f,p;w3) + A(p;w3))
```

**Without offsets (a).** Every position is treated as its own family: `net = gross` for every position, so the offset-credit term disappears. Equivalently, set `net(f,p) = gross(f,p)` in each family; because `r` is constant within a family, this equals the sum of the singleton-position margins. The concentration add-on is **not** a netting offset: it is gross-based and side-blind, so it is computed exactly as in (b) from the same `w3`. Thus:

```
M_without(p) = house_buffer * (sum_f r(f,p) * gross(f,p;w3) + A(p;w3))
```

`A(p;w3)` is identical in (a) and (b) by construction; only the family netting term differs. This isolates netting from reallocation and from the concentration add-on. The house buffer is applied once per PB in both.

**Netting benefit.**

```
NB(p)  = M_without(p) - M_with(p) >= 0
```

because `|sum_i s_i N_i w| <= sum_i N_i w` and `phi >= 0`. S7 checks `M_with(p) <= M_without(p)` at every receiving PB.

**ST0 counterfactual.** The same two constructions at `w0` with the full Phase 1 provider set:

```
M0(p)         = M_with(p;w0)
M_without0(p) = M_without(p;w0)
NB0(p)        = M_without0(p) - M0(p)
```

**Separation identity.** Define:

```
netting_change(p)   = NB0(p) - NB(p)          # positive = netting benefit lost
reallocation(p)     = M_without(p) - M_without0(p)
delta_vs_st0(p)     = M_with(p) - M0(p)
```

Then exactly:

```
delta_vs_st0(p) = reallocation(p) + netting_change(p)
```

`reallocation` is the margin change on a no-offset basis (same netting treatment at ST0 and ST3), so it isolates the position/PB movement and rate differences. `netting_change` is the part explained by the change in within-PB offsets. A positive total `netting_change` means offsets were lost and ST3 margin rises by more than reallocation alone explains (E-S4); a negative total means netting increased on reallocation and E-S4 is not met, reported as found.

For the terminated PB `t`, `w3(i,t) = 0`, so `M_with(t) = M_without(t) = 0` and `NB(t) = 0`. Its ST0 netting benefit appears in full as `netting_change(t) = NB0(t)`, and `delta_vs_st0(t) = -M0(t)`. Including `t` in the table is what makes the loss of the terminated PB's within-PB offsets visible; S7 is checked on the receiving PBs.

#### File layout

Rows: `PB_A`, `PB_B`, `PB_C`, `PB_D`, then `TOTAL`, in that order. `TOTAL` sums every numeric column over all four PBs; the identity holds for each row and for the total. Columns:

| Column | Definition |
|---|---|
| `scenario` | ST3 |
| `pb_id` | PB_A, PB_B, PB_C, PB_D, TOTAL |
| `role` | `receiving` for PB_A/PB_B/PB_C, `terminated` for PB_D, `total` for TOTAL |
| `margin_with_offsets_usd` | `M_with(p)` |
| `margin_without_offsets_usd` | `M_without(p)` |
| `netting_benefit_usd` | `M_without(p) - M_with(p)` |
| `st0_margin_with_offsets_usd` | `M0(p)` |
| `st0_margin_without_offsets_usd` | `M_without0(p)` |
| `st0_netting_benefit_usd` | `NB0(p)` |
| `netting_change_usd` | `NB0(p) - NB(p)` |
| `reallocation_effect_usd` | `M_without(p) - M_without0(p)` |
| `delta_margin_vs_st0_usd` | `M_with(p) - M0(p)` |
| `identity_residual_usd` | `delta_margin_vs_st0_usd - reallocation_effect_usd - netting_change_usd`; must be zero within 1e-6 |

The decomposition is arithmetic, not an estimate. The table shows (a) and (b) separately, the netting benefit at ST0 and ST3, and the additive split into reallocation and netting. No other scenario is decomposed.

### 4.5 `stress_bucket_sensitivity.csv` (supplementary)

One row, not one of the seven scenarios:

| Column | Definition |
|---|---|
| `scenario` | `ST1a_cuts_0.12_0.24` |
| `cut_low` | 0.12 |
| `cut_high` | 0.24 |
| `total_margin_usd` | `M` for ST1a vols re-bucketed with these cuts |
| `delta_margin_vs_st0_usd` | minus ST0 total margin |
| `status` | `optimal` or `infeasible` |

This is the §3.8 one-line sensitivity. It is not used in any other output, test or expected-behaviour check.

### 4.6 Report section "Stress projection (Phase 2a)"

Add one section to the existing `report.build` output:

1. **Summary table** from `stress_summary.csv`: scenario, total margin, Δ margin, additional funding requirement, status, and the three slack columns when infeasible. The table shows all seven rows.
2. **Top-10 moves table** from `stress_moves.csv`: the ten rows with the largest `notional_moved_usd`, descending; ties by scenario order, `pos_id`, `from_pb`, `to_pb`. If there are fewer than ten rows, show all.
3. **ST3 terms line**: terminated PB, `notice_days`, `nav_trigger_pct`, termination date, allocated notional to move and number of positions, from the summary and `stress_moves.csv`.
4. **Bucket sensitivity line**: the one row from `stress_bucket_sensitivity.csv`.
5. **Boundary note**: illustrative static stress, not calibrated, not any firm's methodology; cleared/exchange margin, path dependence and margin-call dynamics are out of scope.

The report reads the CSVs; it does not recompute the stress.

### 4.7 Definition note: additional funding requirement (in the prereg and RESULTS)

"Additional funding requirement" is an **absolute extra-funding requirement against the base case**, in USD:

```
additional_funding_requirement_s = (M_s - M0) + total_slack_s
```

There is no available-liquidity or buffer term, so it is **not** a liquidity-coverage gap and not a forecast. It is the model's extra margin/funding under the scenario, with any constraint violation converted to USD via the Phase 1 slack blocks. For an optimal scenario the slack is zero and the requirement is the margin increase alone. The identity holds for every scenario; S6 checks it.

## 5. Pre-registered expected behaviour (spec §4; directions only, no target numbers)

These are expectations, not pass/fail tuning targets. They are reported as met / not met, as found, in RESULTS.md.

| ID | Expectation | Operational reading (reported as found) |
|---|---|---|
| E-S1 | ST1a, ST1b, ST2a, ST2b and ST4 total margin ≥ ST0. | `M_s >= M0 - 1e-6` for those five scenarios. ST3 is not in E-S1. |
| E-S2 | ST2a moves few or no positions; ST2b moves positions away from the two shocked PBs. | For ST2a and ST2b, report the number/share of positions with any allocation change versus ST0 (`sum_p |w_s - w0| > 1e-9`). For ST2b, report the net allocated notional change at the two shocked PBs; "away" means the total allocated notional at PB_D + PB_A falls versus ST0. No numeric threshold is fixed. |
| E-S3 | In ST3 no position remains at the terminated PB. | `max_i w3(i, PB_D) = 0` within 1e-12; structural because PB_D is removed from the solve. |
| E-S4 | ST3 total margin rises by more than reallocation alone explains, because offsets within the terminated PB are lost. | Using §4.4, total `netting_change_usd > 0` (equivalently `delta_margin_vs_st0 > reallocation_effect`). If total netting change is zero or negative, E-S4 is not met and that is reported. |
| E-S5 | ST4 additional funding requirement ≥ the largest of ST1a, ST2b and ST3. | `AFR_ST4 >= max(AFR_ST1a, AFR_ST2b, AFR_ST3) - 1e-6`. |

E-S2's "few or no" is intentionally descriptive: the pre-registration does not fix a count threshold, because that would turn a directional expectation into a target. The counts are reported.

## 6. Acceptance tests S1–S7 (author; written before `stress.py`)

The tests are `tests/acceptance/test_stress.py` plus a new section in `docs/HAND_WORKED_EXAMPLE.md`. They are the author's, per the authorship rule; the AI assistant does not write them. The pass conditions below are fixed before code.

| # | Test | Pass condition |
|---|---|---|
| S1 | ST0 reproduces `run_42` | ST0 `total_margin_usd`, `financing_usd`, `margin_funding_usd` and `objective_usd` equal `reports/run_42/results/run_summary.csv` to the cent (round both to 2 dp, or absolute difference < 0.005 USD); status `optimal`. |
| S2 | ST1a/ST1b re-bucketing, hand-worked | `CDS_ISS003` moves V1→V2 and `CE_ISS008` moves V2→V3 under both multipliers, exactly as the cut rule says, using the hand-worked arithmetic in `docs/HAND_WORKED_EXAMPLE.md`. |
| S3 | ST2a at fixed ST0 allocation | At `w0`, for every PB, `family_margin` before add-on and house buffer is `1.5 ×` the ST0 value within 1e-6 USD absolute or 1e-9 relative, whichever is looser; the concentration add-on is unchanged within 1e-6 USD because it uses `conc_rate`; `base_rate` is 1.5 × everywhere and `financing_spread_bps` is unchanged. |
| S4 | ST2b at fixed ST0 allocation | At `w0`, `base_rate` is unchanged at the unshocked PBs and 1.5 × at the two shocked PBs; `family_margin` is 1.5 × ST0 at the two shocked PBs and unchanged at the others; the add-on is unchanged; `financing_spread_bps` is unchanged. |
| S5 | ST3 termination | `w3(i, PB_D) = 0` for every position. If status is `optimal`, no slack; if `infeasible`, status is exactly `infeasible` and `total_slack_usd > 0` with at least one block amount > 1e-6. |
| S6 | Additional-funding-requirement identity | For every scenario, `additional_funding_requirement_usd = delta_margin_usd + total_slack_usd` within 1e-6 USD, and `total_slack_usd` equals the sum of the three slack columns within 1e-6. For optimal scenarios all slacks are 0. |
| S7 | ST3 netting decomposition | For every receiving PB (`PB_A`, `PB_B`, `PB_C`), `margin_with_offsets_usd <= margin_without_offsets_usd + 1e-6`; the total also satisfies it. |

### 6.1 S2 hand-worked inputs (fixed)

Window: last 60 close-to-close log returns with date ≤ 2026-10-30; first return 2026-08-10, last 2026-10-30; sample std `ddof=1`; annualise by `sqrt(252)`.

| Product | ST0 annualised vol | ST0 bucket | ×2 vol | ST1a bucket | ×1.5 vol | ST1b bucket |
|---|---:|---|---:|---|---:|---|
| `CDS_ISS003` | 0.090769468946 | V1 | 0.181538937892 | V2 | 0.136154203419 | V2 |
| `CE_ISS008` | 0.193704438203 | V2 | 0.387408876406 | V3 | 0.290556657304 | V3 |

These are the hand-worked targets; the new `docs/HAND_WORKED_EXAMPLE.md` section must show the return window and the cut arithmetic. They are input-transformation checks, not margin targets.

### 6.2 S3 note

S3 is evaluated at the **fixed ST0 allocation** `w0`, not at the re-optimised ST2a allocation. At `w0`, gross and net exposures are unchanged, so each family's `r` scales by exactly 1.5 and its family margin follows; the add-on uses `conc_rate` and is unchanged. Total margin is `1.15 * (1.5 * FM0 + addon0)`, which is generally not `1.5 * M0`. The test must not assert `M_ST2a = 1.5 * M0`.

### 6.3 S6 note

The identity is checked on the CSV values as written, not on unrounded internal values. `additional_funding_requirement_usd` is computed from `delta_margin_usd + total_slack_usd`; a writer or rounding error fails the test. For an infeasible scenario, the cost columns are NaN but the identity still holds because it uses margin and slack, not cost.

## 7. Fixed Phase 2a facts for the primary case

These are data facts from `run_42` and `providers.csv`, recorded before code so the scenario identities are unambiguous. They are not Phase 2a results and not targets.

| Fact | Value |
|---|---|
| ST0 total margin | 1,747,690,859.463315 |
| ST0 margin PB_A | 477,120,106.135151 |
| ST0 margin PB_B | 211,730,389.000000 |
| ST0 margin PB_C | 293,929,811.492475 |
| ST0 margin PB_D | 764,910,552.835689 |
| ST0 top two PBs | PB_D, PB_A |
| Terminated PB | PB_D |
| PB_D notice / NAV trigger | 126 days / 29.1% |
| PB_D termination date | 2027-03-05 |
| PB_D capacity | 3,948,127,000 |
| Notional allocated to PB_D at ST0 | 2,912,025,250.525632 |
| Positions with any allocation at PB_D at ST0 | 106 of 214 |
| Held products | 73 |
| ST1a bucket moves / V3 saturation | 27 move (9 V1→V2, 18 V2→V3); 42 stay V3 |
| ST1b bucket moves | 22 |

The rules in §3.1–§3.7, not these names, are normative. If the data change so that a different PB is largest, the rule selects the new PB and the change is a deviation, not a silent re-interpretation.

## 8. Changes, deviations and what this document does not do

- **No Phase 1 change.** M1–M3 formulas, `run_42` outputs and A1–A7 are untouched. The stress module reads the Phase 1 case and calls the existing optimiser/margin functions.
- **No new data or parameters.** `data/raw/*`, `data/SOURCES.md` and `params.csv` are unchanged. The scenario transforms are code, not data.
- **No results in this document.** Expected behaviour is directional only. The Phase 2a results, E-S1–E-S5 outcomes and summary table go in `RESULTS.md`, as found.
- **No cleared/exchange margin, path dependence, margin-call dynamics or liquidity buffer.** See §1.3 and §1.4.
- **Deviations.** Any change to a multiplier, a PB choice, the notice/timing convention, the locate relaxation, an output column, a tolerance or a test is logged in `prereg/DEVIATIONS.md` with date, reason and effect. Nothing here is edited after the prereg commit.
- **Implementation boundary.** `src/mfl/stress.py` and S1–S7 are the author's. The AI assistant's plumbing (CLI, report, CSV writers, plumbing tests, CI, docs drafts) must not contain stress logic; if it needs a missing function it stubs it with `NotImplementedError` and stops.
