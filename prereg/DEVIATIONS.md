# Deviations from the pre-registration

Each entry: date · what changed · why · effect on results · commit.

## D-01 · 2026-11-18 · Sensitivity grid: add liquidity premium ℓ ∈ {100, 300, 500} bps
- What: §8 sensitivity grid gains three runs varying `liquidity_premium_bps` (100 = primary, 300, 500); everything else fixed.
- Why: a pre-run feasibility check on the synthetic data showed financing spreads dominate the objective at ℓ = 100 bps, so margin shapes the allocation mainly through counterparty limits. Varying ℓ shows when margin cost starts to move the allocation.
- Effect: additional exhibit only; primary run, tests and charge unchanged. Decided before any model code or results.
- Commit: (this commit)
