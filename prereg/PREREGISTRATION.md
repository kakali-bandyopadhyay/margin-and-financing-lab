# Pre-registration – margin-and-financing-lab (Phase 1)

Status: DRAFT seeded 18 Nov 2026 from build spec v0.3 – reviewed against v0.3; C1–C4 confirmed and §7 values checked 18 Nov 2026. Author to review and commit before any model code (`src/mfl/margin.py`, `optimise.py`, `attribution.py`).
Rule: once committed, any change to the model, tests, parameters or reported outputs is logged in `prereg/DEVIATIONS.md` with date, reason and effect. Nothing here is edited after model code exists.

## 1. Purpose and boundary
Allocate a synthetic multi-asset hedge-fund book across synthetic prime brokers (PBs) at minimum currency cost over a stated horizon, under a transparent margin proxy, and attribute margin usage and an illustrative internal charge to portfolio managers (PMs).
Boundary: not a portfolio-margin model; not calibrated to any provider; offsets approximated; synthetic data; illustrative charge policy; outputs describe model behaviour, not prediction. The model is not validated (see `docs/MODEL_DOC.md`).

## 2. Data contract
One table per CSV in `data/raw/`, loaded into DuckDB. Generated synthetically; provenance in `data/SOURCES.md`.

| Table | Key | Fields |
|---|---|---|
| pms | pm_id | strategy, asset_class_focus |
| issuers | issuer_id | asset_class, sector, adv_usd, conc_eligible (bool) |
| products | product_id | asset_class (exactly one), product_type, issuer_id (nullable), needs_locate (bool) |
| positions | pos_id | pm_id, product_id, side (+1/−1), notional_usd (>0), liquidity_tier (L1–L3) |
| price_history | product_id, date | close |
| providers | pb_id | capacity_usd, counterparty_limit_usd, conc_threshold θ_p, conc_rate c_p, lockup_days, notice_days, nav_trigger_pct |
| pb_rates | pb_id, product_id, liquidity_tier | base_rate, financing_spread_bps, phi |
| pb_borrow | pb_id, issuer_id | borrow_fee_bps, borrow_available_usd (0 = no locate) |
| params | name | see §7 |

product_type ∈ {cash_equity, equity_swap, govt_bond, irs_proxy_future, fx_forward, commodity_future, cds_proxy}.
vol_bucket is derived at load (§3.1), never supplied.

Load-time validation (file rejected on any failure):
- base_rate > 0 and 0 ≤ phi < 1 on every pb_rates row; 0 < θ_p < 1 and c_p ≥ 0 on every provider.
- every position has a pb_rates row at every PB for its (product, tier); asset class implied by product (one class per product).
- issuer_id present iff product_type ∈ {cash_equity, equity_swap, govt_bond, cds_proxy}; needs_locate = TRUE only for cash_equity, equity_swap, govt_bond.
- conc_eligible = TRUE only for corporate equity and credit issuers; sovereign issuers must be FALSE. Products without an issuer (FX forwards, IRS-proxy futures, commodity futures) receive no concentration add-on.
- notional_usd > 0; side ∈ {+1, −1}; params complete; liquidity_premium_bps ≥ 0.
- every number in params and every column in the CSVs has a provenance tag in `data/SOURCES.md`.

Confirmed clarifications of spec v0.3 (18 Nov 2026):
- C1 θ and c are per PB (`providers`), not per product row; the offset share φ stays per (PB, product, tier). Phase 1 data uses θ = 0.25, c = 0.02, φ = 0.60 everywhere, so results match the spec; the schema allows Phase 2 variation.
- C2 Concentration applies only to corporate issuers with `conc_eligible = TRUE` (corporate equity and credit issuers). Sovereign issuers are `FALSE`; FX forwards, IRS-proxy futures and commodity futures have no concentration add-on.
- C3 Funding cost k(i,p): longs pay `financing_spread_bps`; shorts with `needs_locate = TRUE` pay the `borrow_fee_bps` for (PB, issuer) where a locate is available. Their allocation is zero at a PB with no locate or zero availability, so no borrow fee is incurred there. Shorts that do not need a locate, including derivatives, pay `financing_spread_bps`.
- C4 A PM's solo margin is M evaluated on that PM's positions alone at the optimal allocation w* (no re-solve or reallocation after removal). Primary usage remains fixed-allocation leave-one-out; u_k may be negative and credits are allowed.

## 3. M1 – Margin proxy
Decision variable w(i,p) ∈ [0,1], Σ_p w(i,p) = 1. Side s_i and notional N_i are data, so every exposure is linear in w.

3.1 Volatility bucket (input): last 60 daily close-to-close log returns up to params.as_of_date, sample std (ddof = 1) × √252. < 10% → V1; 10–20% → V2; > 20% → V3; fewer than 60 returns → V3. Multipliers V1 1.0, V2 1.3, V3 1.8. Cut-offs and multipliers are assumptions.

3.2 Family f = (product, liquidity_tier, vol_bucket). Netting is per PB; no cross-PB netting.
- gross(f,p) = Σ_{i∈f} N_i·w(i,p)
- net(f,p) = |Σ_{i∈f} s_i·N_i·w(i,p)|
- r(f,p) = base_rate(p, product, tier) × mult(bucket)
- FM(f,p) = r(f,p)·[φ·net(f,p) + (1−φ)·gross(f,p)]

3.3 Concentration, per conc-eligible issuer g at PB p:
- G(g,p) = Σ_{i∈g} N_i·w(i,p); G(p) = Σ_i N_i·w(i,p)
- add-on(g,p) = c_p·max(0, G(g,p) − θ_p·G(p))

3.4 M(p) = 1.15 × (Σ_f FM(f,p) + Σ_g add-on(g,p)); M = Σ_p M(p).
Properties claimed (tested in §6): zero at zero, non-negative, convex, piecewise linear, positively homogeneous of degree 1.
Reported margin is always recomputed from w* by `margin.py`, never read from solver epigraph variables.

## 4. M2 – Allocation optimiser
Objective (USD over H days, ACT/360; the benchmark rate is common to all PBs and drops out):
min Σ_{i,p} N_i·w(i,p)·k(i,p)·1e-4·H/360 + Σ_p M(p)·ℓ·1e-4·H/360

Constraint blocks (cost terms never inside them):
1. Σ_p w(i,p) = 1; w ≥ 0.
2. Capacity: G(p) ≤ capacity_usd(p).
3. Counterparty: M(p) ≤ counterparty_limit_usd(p) (constant; never M(p) ≤ κ·M).
4. Borrow: Σ_{short i, needs_locate, issuer g} N_i·w(i,p) ≤ borrow_available_usd(p,g); w(i,p) = 0 where no locate row or available = 0.

Formulation: LP via cvxpy + HiGHS; |·| and max(0,·) by epigraph variables. Solver status checked; if infeasible, re-solve with penalised slacks per block and report which block(s) needed slack. Duals reported for blocks 2–4 as sensitivity only (may be non-unique under degeneracy). Epigraph tightness checked: recomputed M(p) equals the solver's M(p) within 1e-6 when ℓ > 0.
Any fixed fee, minimum balance or activation binary would make this a MILP – out of Phase 1 scope; logged in DEVIATIONS.md if introduced.

## 5. M3 – PM usage and illustrative charge
- Primary usage (fixed-allocation leave-one-out): u_k = M(w*) − M(w* with PM k's positions removed), no re-solve. u_k may be negative (a PM whose positions offset others' or dilute concentration lowers book margin) – credits allowed.
- Sensitivity exhibit: remove PM k, re-optimise the rest, recompute M; reported separately, never used for the charge.
- Solo margin M_k^solo = M evaluated on PM k's positions alone at the optimal allocation w* (C4 confirmed; no re-solve or reallocation after removal).
- Residual R = M − Σ_k u_k, assigned by share_k = M_k^solo / Σ_j M_j^solo.
- Zero-denominator rule: with base_rate > 0 and φ < 1 validated at load, any position with N_i > 0 has margin ≥ 1.15·(1−φ)·r·N_i > 0, so Σ_j M_j^solo = 0 only for an empty book. Then share_k = 0 for all k and |R| ≤ 1e-9 is asserted; any other zero denominator raises an error. A PM with no positions gets share 0.
- Charge_k = (u_k + share_k·R) × pass_through_bps × 1e-4 × H/360.
- Separate exhibits: all-in cost attribution (financing + margin funding); Euler allocation (subgradient at w*; sums to M except at kinks – kinks reported); Aumann–Shapley exploratory.

## 6. Acceptance tests (written before model code; `tests/acceptance/`)
| # | Test | Pass condition |
|---|---|---|
| A1 | Hand-worked example (§6.1) | M(p), M, u_k, R, charges match `docs/HAND_WORKED_EXAMPLE.md` to the cent |
| A2a | Zero at zero | all w = 0 or empty book → M = 0 |
| A2b | Non-negative | M(p) ≥ 0 on 1,000 random feasible w (seed 42) |
| A2c | Monotone in size | scaling one position up (no offsetting position in its family at that PB) never lowers M |
| A2d | Monotone in bucket | moving a family V1→V2→V3 never lowers M |
| A2e | Convexity | M((w_a+w_b)/2) ≤ (M(w_a)+M(w_b))/2 + 1e-6 on 1,000 random pairs |
| A2f | Homogeneity | M(λN) = λ·M(N) within 1e-9·M for λ ∈ {0.5, 2, 10} |
| A2g | Determinism | two runs with seed 42 give identical outputs |
| A3 | Offset credit | for one hedged family before add-on/buffer: FM = r·gross − φ·(gross − net)·r |
| A4 | No cross-PB netting | equal-and-opposite pair, same r at both PBs: split across two PBs → strictly higher M than both at one PB |
| A5 | Constraints | all blocks hold within 1e-6; status checked; a deliberately infeasible case returns the blocking block(s) |
| A6a | Attribution adds up | Σ_k (u_k + share_k·R) = M within 1e-6 USD |
| A6b | Order independence | permuting PM order leaves every u_k and charge unchanged |
| A6c | Zero-denominator cases | empty book → all charges 0; a PM with no positions → share 0; base_rate = 0 or φ = 1 in a file → rejected at load |
| A7 | Matched-product sanity | proxy margin for one matched product within a stated band of one published exchange margin (sanity only, source in SOURCES.md) |
| A8 | Not-validated statement | `docs/MODEL_DOC.md` contains the "not validated" statement |

6.1 Hand-worked example inputs and expected values (record/reproduce in `docs/HAND_WORKED_EXAMPLE.md` before code):
- PBs: X, Y. Buffer 1.15; φ 0.60; θ 0.25; c 0.02; H 90; pass-through 100 bps.
- P1: PM A, long cash equity on issuer I1 (conc-eligible), N = 10,000,000, L1, V3.
- P2: PM B, short the same product, N = 6,000,000, L1, V3.
- P3: PM A, long govt bond (sovereign, not conc-eligible), N = 20,000,000, L1, V1.
- base_rate: equity L1 X 0.15, Y 0.18; govt bond L1 X 0.02, Y 0.015.
- Case (a): all positions at X. Case (b): P1 at X; P2 and P3 at Y.
- Compute for each case: FM per family, add-on, M(X), M(Y), M; then u_A, u_B, M_A^solo, M_B^solo, R, shares and charges.

Expected values below use the fixed placements stated for each case; amounts are USD. Recompute each PB's concentration threshold from the gross remaining in that book for the full portfolio, each leave-one-out book, and each PM's solo margin. Charges use 100 bps × 90/360 = 0.0025. Shares are shown to 10 decimal places; compute charges from unrounded shares.

| Case | PB | FM by family | Concentration add-on | M(PB) |
|---|---|---|---:|---:|
| (a) | X | Equity: 2,376,000; govt bond: 400,000 | 140,000 | 3,353,400 |
| (a) | Y | 0 | 0 | 0 |
| (b) | X | Equity: 2,700,000 | 150,000 | 3,277,500 |
| (b) | Y | Equity: 1,944,000; govt bond: 300,000 | 0 | 2,580,600 |

| Case | M | u_A | u_B | M_A^solo | M_B^solo | R | share_A | share_B | Charge_A | Charge_B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| (a) | 3,353,400 | 1,386,900 | -269,100 | 3,622,500 | 1,966,500 | 2,235,600 | 0.6481481481 | 0.3518518519 | 7,089.75 | 1,293.75 |
| (b) | 5,858,100 | 3,519,000 | 2,235,600 | 3,622,500 | 2,339,100 | 103,500 | 0.6076388889 | 0.3923611111 | 8,954.73 | 5,690.52 |

## 7. Parameters (fixed for the primary run)
| name | value | tag |
|---|---|---|
| as_of_date | 2026-10-30 | assumed (synthetic calendar end) |
| horizon_days H | 90 | assumed (one quarter) |
| liquidity_premium_bps ℓ | 100 | assumed (fund's cost of cash locked as margin) |
| house_buffer | 1.15 | assumed |
| pass_through_bps | 100 | assumed (equal to ℓ: charge passes the margin funding premium through) |
| phi φ | 0.60 | assumed |
| conc_threshold θ | 0.25 | assumed (D2) |
| conc_rate c | 0.02 | assumed |
| vol cut-offs | 10% / 20% | assumed (D1) |
| vol multipliers | 1.0 / 1.3 / 1.8 | assumed (D1) |
| seed | 42 | – |

Checked against build spec v0.3: liquidity premium = 100 bps, pass-through = 100 bps, horizon = 90 days, and as-of date = 2026-10-30 (30 Oct 2026); all four values match.

## 8. Outputs reported (all of them, whatever they show)
`python -m mfl.cli run --seed 42` → `reports/run_42/report.html` + CSVs: allocation by PB; margin by PB / family / issuer; binding constraints + duals; PM usage and charge; re-solve sensitivity; Euler exhibit with kinks; sensitivity grid (vol bucket +1 for all families; base_rate × 1.25; θ 0.20 and 0.30). Report tables come from `sql/*.sql` on DuckDB.

## 9. Expected behaviour (stated before the first run; reported as confirmed / not confirmed)
- E1 Hedged pairs inside a family concentrate at one PB rather than splitting (A4 logic), unless capacity or borrow forces a split.
- E2 At least one capacity or counterparty constraint binds; the cheapest PB on financing is not the sole PB used.
- E3 Shorts in issuers with locate at only one PB sit at that PB; tight locate shows a positive borrow dual.
- E4 At least one PM has u_k < 0 (offset or dilution credit).
- E5 Raising θ from 0.25 to 0.30 lowers M; lowering it to 0.20 raises M (weakly).

## 10. Out of scope (Phase 2)
Stress module (vol shock, haircut hike, PB notice/lock-up, margin-call projection); synthetic calibration (parameter recovery); MILP variant.
