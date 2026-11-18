# Data sources and provenance

Every number the model uses carries one tag: **source** (public citation with date), **assumed** (with reason) or **to-be-calibrated** (Phase 2). Untaggable numbers are not admitted.

## 1. Synthetic tables (data/raw/)
| File | Generator | Date | Prompt / script | Rows | Checks passed | Tag |
|---|---|---|---|---|---|---|
| pms.csv | DeepSeek | | | | | assumed – synthetic |
| issuers.csv | DeepSeek | | | | | assumed – synthetic |
| products.csv | DeepSeek | | | | | assumed – synthetic |
| providers.csv | DeepSeek | | | | | assumed – synthetic |
| price_history.csv | DeepSeek script (seeded) | | | | | assumed – synthetic |
| positions.csv | DeepSeek | | | | | assumed – synthetic |
| pb_rates.csv | DeepSeek | | | | | assumed – synthetic |
| pb_borrow.csv | DeepSeek | | | | | assumed – synthetic |

## 2. Coefficient ranges used in generation
| Coefficient | Range given to the generator | Tag | Reason |
|---|---|---|---|
| base_rate (by product type, L1) | | assumed | |
| liquidity-tier uplift (L2, L3) | | assumed | |
| financing_spread_bps (longs) | | assumed | |
| borrow_fee_bps (general / hard-to-borrow) | | assumed | |
| capacity_usd, counterparty_limit_usd | | assumed | sized so at least one PB binds |
| target annualised vol by product type | | assumed | spreads products across V1–V3 |

## 3. Model parameters (data/raw/params.csv)
| name | value | tag | reason |
|---|---|---|---|
| as_of_date | 2026-10-30 | assumed | synthetic calendar end |
| horizon_days | 90 | assumed | one quarter |
| liquidity_premium_bps | 100 | assumed | fund's cost of cash locked as margin |
| house_buffer | 1.15 | assumed | |
| pass_through_bps | 100 | assumed | equal to the liquidity premium |
| phi | 0.60 | assumed | |
| conc_threshold | 0.25 | assumed | account-relative (D2) |
| conc_rate | 0.02 | assumed | |
| vol cut-offs | 0.10 / 0.20 | assumed | D1 |
| vol multipliers | 1.0 / 1.3 / 1.8 | assumed | D1 |
| seed | 42 | – | |

## 4. Public sources (sanity check A7 only)
| Item | Source | Date accessed | Value | Used for |
|---|---|---|---|---|
| Published exchange margin for one matched product | | | | A7 sanity band – not calibration |
