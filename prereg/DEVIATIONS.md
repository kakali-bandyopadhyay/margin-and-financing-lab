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
