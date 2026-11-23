# Data sources and provenance

Every number the model uses carries one tag: **source** (public citation with date), **assumed** (with reason) or **to-be-calibrated** (Phase 2). Untaggable numbers are not admitted.

## 1. Synthetic tables (data/raw/)
| File | Generator | Date | Prompt / script | Rows | Checks passed | Tag |
|---|---|---|---|---|---|---|
| pms.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B | 10 | structure + realism (Claude) | assumed – synthetic |
| issuers.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B | 44 | structure + realism (Claude) | assumed – synthetic |
| products.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B | 77 | structure + realism (Claude) | assumed – synthetic |
| providers.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B + fix C | 4 | structure + realism (Claude) | assumed – synthetic |
| price_history.csv | DeepSeek script (seeded) | 2026-11-18 | DeepSeek prompts A/B | 9,669 | structure + realism (Claude) | assumed – synthetic |
| positions.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B + fix C | 214 | structure + realism (Claude) | assumed – synthetic |
| pb_rates.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B + fix C | 924 | structure + realism (Claude) | assumed – synthetic |
| pb_borrow.csv | DeepSeek | 2026-11-18 | DeepSeek prompts A/B | 176 | structure + realism (Claude) | assumed – synthetic |

### Revision log
| Date | File | Change | Reason |
|---|---|---|---|
| 2026-11-18 | providers, positions, pb_rates | DeepSeek fix C: counterparty limits re-drawn; liquidity tier set from the PM's total position per (PM, product, side); equity/govt-bond rates re-drawn so the cheapest-margin PB differs from the cheapest-financing PB; L1 < L2 < L3 spreads | A/B check: limits below estimated book margin; tiers set per lot; no margin-vs-financing trade-off; 14 spread-order breaks |
| 2026-11-18 | providers | counterparty_limit_usd × 1.25 (applied by Claude after an LP feasibility check) | at fix-C limits the minimum achievable margin used 98% of total limits (3 of 4 binding); ×1.25 leaves one binding limit (PB_B) |

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
| CBOT ZN Dec-26 outright non-HRP initial margin and settlement | CME Group ZN margins and settlements pages | 2026-11-18 | Initial $1,875; maintenance $1,875; settle 105.609375 (105'19.5); multiplier $1,000/point; margin snapshot/effective date 2026-11-17 | A7 sanity band – not calibration |

## 5. Phase 2b calibration proxies

| Proxy use | Source / series | Field and transformation | Window | Provenance / limitation |
|---|---|---|---|---|
| `irs_proxy_future`, `govt_bond` | FRED DGS10 | Daily 10-year Treasury yield; converted to a duration-based price return using the frozen 10-year par-bond duration in `calibration_proxies.csv` | 2015-01-01 through 2026-10-30 | Public domain; illustrative rates proxy, not maturity- or currency-matched |
| `fx_forward` | FRED DEXUSEU | USD-per-EUR rate; daily log change | 2015-01-01 through 2026-10-30 | Public domain; stands in for other pairs and omits forward points |
| `cash_equity`, `equity_swap` | Tiingo SPY | Daily `adjClose`; log return | 2015-01-01 through 2026-10-30 | Free plan; raw prices are git-ignored; index proxy understates single-name and swap-specific risks |
| `commodity_future` | Tiingo GLD | Daily `adjClose`; log return | 2015-01-01 through 2026-10-30 | Free plan; raw prices are git-ignored; spot-gold proxy for other commodities, without roll yield or contango |
| `cds_proxy` | Tiingo HYG | Daily `adjClose`; log return | 2015-01-01 through 2026-10-30 | Free plan; raw prices are git-ignored; total-return ETF mixes credit spread, rates, carry and ETF/NAV effects |

Tiingo terms checked before fetching: Free plan; raw price redistribution is not permitted. Only derived statistics and input digests are committed. FRED series are public domain and are committed. Fixed calibration end date: 2026-10-30. Fetch date: `2026-11-23`. The committed `calibration_inputs_digest.csv` records the normalized raw-input and daily-return hashes; reproduction is conditional on identical or tolerance-equivalent fetched observations as described in the Phase 2b pre-registration.
