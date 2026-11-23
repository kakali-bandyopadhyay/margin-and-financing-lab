# Deviations from the pre-registration

Each entry: date · what changed · why · effect on results · commit.

## D-01 · 2026-11-18 · Sensitivity grid: add liquidity premium ℓ ∈ {100, 300, 500} bps
- What: §8 sensitivity grid gains three runs varying `liquidity_premium_bps` (100 = primary, 300, 500); everything else fixed.
- Why: a pre-run feasibility check on the synthetic data showed financing spreads dominate the objective at ℓ = 100 bps, so margin shapes the allocation mainly through counterparty limits. Varying ℓ shows when margin cost starts to move the allocation.
- Effect: additional exhibit only; primary run, tests and charge unchanged. Decided before any model code or results.
- Commit: (this commit)

## D-06 · 2026-11-18 · A7 matched-product exchange-margin sanity check
- What: A7 compares IRSF_10Y with the CBOT 10-Year T-Note futures front contract ZNZ26 using the preselected proxy-to-exchange margin ratio band 0.5–4.0. The CME non-HRP outright initial margin is 100% of maintenance; the 2026-11-17 CME margin snapshot lists maintenance at $1,875. The same-day CME settlement is 105'19.5 (105.609375), with a $1,000-per-point multiplier.
- Why: a wide sanity band catches unit and scale errors; it is not calibration. The band was fixed before checking the CME figure. An indicative broker-reported $2,062.50 figure seen earlier was disclosed and was not used as the exchange margin.
- Effect: test only; no model rates or primary results change.
- Commit: (this commit)

## D-02 · 2026-11-18 · Margin evaluation speed: prebuilt index (refactor + A2 test runtime)
- What: `margin.py` `margin_by_pb` and `total_margin` accept an optional prebuilt `index` (from `build_index`) and compute M(p) with NumPy only; `margin_detail` unchanged. A2b, A2e and A2g build the index once and pass it; `optimise.py` passes the index it already builds.
- Why: every margin call rebuilt the rate index with pandas merges (~12 ms per call); the acceptance suite took ~110 s.
- Effect: no change to formulas, parameters, draws, tolerances or assertions. A1 unchanged to the cent; A5 ℓ = 100 objective unchanged (21,714,337.24). Suite runtime ~110 s → ~3 s.
- Commit: (this commit)

## D-03 · 2026-11-18 · Attribution: reject pm_ids that omit a PM in the book (test after model code)
- What: `pm_usage` raises ValueError when an explicit `pm_ids` leaves out a `pm_id` present in the book; acceptance test added to A6c.
- Why: found in Claude review of 5ce9d22 – an omitted PM's margin fell silently into R and was charged to the listed PMs (Σ still = M, so no check fired). Test written after the model code, hence logged.
- Effect: none on reported results – the primary run passes every PM in pms.csv.
- Commit: (this commit)

## D-04 · 2026-11-18 · M3 exhibits: tests X1–X3 added; Euler wording corrected
- What: acceptance tests X1 (re-solve), X2 (all-in cost), and X3 (Euler with kinks) added before `exhibits.py`. The X3d hand-case fixture was corrected during implementation to label the govt-bond position as PM B, as specified. Prereg §5 “Euler sums to M except at kinks” corrected: for a convex degree-one homogeneous proxy every subgradient sums to M; kinks make the per-PM split non-unique, so each PM's Euler value is reported with a [low, high] range. Aumann–Shapley equals Euler where Euler is unique (gradient constant along the ray); not computed separately.
- Why: the original statement is mathematically inexact; the tests pin the corrected behaviour.
- Effect: none on the primary usage, residual, or charge; exhibit content as pre-registered (kinks still reported).
- Commit: (this commit)

## D-05 · 2026-11-18 · Euler exhibit: reject omitted PMs and check total
- What: `euler_allocation` raises ValueError when explicit `pm_ids` omit a PM present in the book and checks that reported Euler values sum to M; an acceptance test covers the omitted-PM case.
- Why: like the D-03 usage gap, an omitted PM's Euler contribution could silently disappear from the per-PM exhibit. The total check guards the exhibit decomposition.
- Effect: no change to reported numbers; the primary run includes every PM and continues to match M.
- Commit: (this commit)

## D-07 · 2026-11-18 · A8 model-document disclosure test
- What: `tests/acceptance/test_a8_not_validated.py` checks that the model document contains the required validation-status sentence exactly once and presents its 15 numbered headings in order.
- Why: pin the required model-document outline and disclosure before the documentation is finalised.
- Effect: documentation control only; no model calculations or results change.
- Commit: (this commit)

## D-08 · 2026-11-18 · Enforce the pre-registered input contract at load
- What: `io.py` rejects invalid PB concentration terms, parameter domains, product/issuer/locate combinations, ineligible concentration flags, invalid positions, duplicate or missing rate keys, missing price history, and missing provenance tags in SOURCES.md.
- Why: these checks were promised in pre-registration §2 but were not enforced at load; the loader should reject inputs outside that contract before modelling.
- Effect: the existing synthetic input remains unchanged; plumbing tests exercise the rejection cases.
- Commit: (this commit)

## D-09 · 2026-11-22 · Stress solver retry: CLARABEL when HiGHS returns UNKNOWN
- What: `src/mfl/stress.py` adds a contained solver retry. If HiGHS returns an unpackable `UNKNOWN` solution, the same cvxpy problem is re-solved with CLARABEL. The retry monkeypatches `cvxpy.Problem.solve` for the duration of each stress optimiser call and restores it in a `finally` block. In the primary case the observed trigger is ST2b; HiGHS reports that LP as `UNKNOWN`, CLARABEL identifies it as infeasible, and the Phase 1 slack re-solve then runs.
- Why: prereg §2.3 fixes the solver settings as unchanged. HiGHS returning `UNKNOWN` prevents the existing optimiser from reaching its infeasible/slack branch, so the pre-registered ST2b status and slack outputs cannot otherwise be produced. The alternative would have been to change Phase 1 `optimise.py`; the fallback is local to `stress.py`.
- Effect: ST2b's status and slacks come from the CLARABEL-retried solve. ST0, ST1a, ST1b, ST2a, ST3 and ST4 use HiGHS normally; CLARABEL is used only after an UNKNOWN result. Phase 1 code, formulas, `run_42` outputs and A1–A7 are unchanged. The global cvxpy patch is not thread-safe and is active only inside `stress.py` optimiser calls; the retry emits a cvxpy backend warning. This is a solver-setting change not in the pre-registration.
- Commit: (uncommitted)

## D-10 · 2026-11-22 · ST3/ST4 locate relaxation uses 1e-9 USD for zero availability
- What: For ST3 and ST4, `_relaxed_borrow` replaces `borrow_available_usd == 0` with `1e-9` USD at the remaining PBs so the Phase 1 `funding_rates` mask allows the cell. The no-slack solve therefore has a borrow RHS of `1e-9` instead of exactly `0`. The borrow shortfall is still computed against the original zero availability and reported as `slack_borrow_usd`.
- Why: `POS0076` and `POS0098` (issuer `ISS010`) need a locate that is available only at the terminated PB_D. Removing PB_D would otherwise raise "no allowed PB" before the slack re-solve, instead of producing the pre-registered infeasible-with-borrow-slack ST3 result. The `1e-9` is a numerical enabler, not an economic amount.
- Effect: The ST3/ST4 no-slack borrow RHS is `1e-9` rather than `0`; reported borrow slack changes by at most `1e-9` USD because `_slack_amounts` uses the original `0`. ST0–ST2b and Phase 1 are unchanged. The prereg §3.6 statement that the no-slack solve enforces `available = 0` is no longer literally true for these two scenarios.
- Commit: (uncommitted)

