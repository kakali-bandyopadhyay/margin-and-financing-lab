# Pre-registration – Phase 2b: margin-rate calibration and exchange-margin drivers

**Status:** This addendum fixes the data proxies, transforms, calibration, backtest, drivers, outputs and tests before data are fetched or the calibration core is implemented. Changes after approval are logged in `prereg/DEVIATIONS.md` with their reason and effect.

**Baseline:** Phase 1 primary case, seed 42, `as_of_date` 2026-10-30, 90-day horizon. Phase 1 and Phase 2a inputs, code and outputs are unchanged.

**Authorship:** The author owns this pre-registration, the calibration core and acceptance tests C1–C5. AI-assisted work covers the data-fetch and digest utilities, pipeline around the core, CLI, separate report builder, plumbing, and tests C6–C13. Synthetic inputs are not added.

## 1. Purpose, scope and boundary

Phase 1 base rates are synthetic. Phase 2b scales those rates by product type to targets estimated from public-market proxies, evaluates target exceedances in a walk-forward backtest, examines rate-model drivers, and re-runs the Phase 1 allocation and pass-through calculation. This is a development exercise using illustrative proxies; calibration to proxies is not independent validation or calibration to an actual provider.

In scope: seven product types, proxy-based expected-shortfall targets, an assumed margin period of risk (MPOR) by product type, the fixed walk-forward backtest, an IRSF driver exhibit and comparison to a published exchange initial-margin observation, plus a re-run of the existing Phase 1 allocation and pass-through charge on scaled rates.

## 2. Data, product types and transforms

### 2.1 Product-type inputs and fixed proxies

`pb_rates.csv` is joined to `products.csv` on `product_id`; every rate row must match exactly one product. The Phase 1 inputs contain 77 products, four PBs and three tiers, for 924 rate rows and seven product types. Proxies are illustrative broad-market stand-ins, not maturity- or instrument-matched calibration. MPORs are fixed modeling assumptions, not claims about a PB agreement or regulatory requirements.

| Product type | Products | Proxy / source | Assumed MPOR (trading days) |
|---|---|---|---:|
| `irs_proxy_future` | IRSF_2Y, IRSF_5Y, IRSF_10Y | DGS10 / FRED | 2 |
| `commodity_future` | COMF_BRENT, COMF_GOLD, COMF_COPPER, COMF_NATGAS | GLD / Tiingo | 2 |
| `cds_proxy` | Eight CDS_ISS products | HYG / Tiingo | 5 |
| `cash_equity` | 40 CE_ISS products | SPY / Tiingo | 10 |
| `equity_swap` | 14 ES_ISS products | SPY / Tiingo | 10 |
| `fx_forward` | Four FXF products | DEXUSEU / FRED | 10 |
| `govt_bond` | GB_SOV01–04 | DGS10 / FRED | 10 |

The exact symbols, source fields, return types, duration placeholders and one-sentence limitations are fixed in `data/public/calibration_proxies.csv` before any data are fetched.

### 2.2 Data window and handling

Daily observations run from 2015-01-01 through the Phase 1 `as_of_date` 2026-10-30. Each proxy uses its own valid-observation calendar; FRED missing-value markers are dropped, and returns are calculated between consecutive valid observations. Fetch date is recorded in `data/SOURCES.md` §5. Raw Tiingo prices remain git-ignored; only derived statistics are committed. Tiingo Free plan terms are checked before fetching. FRED source files are public domain and may be committed.

### 2.3 Proxy return construction and limitations

- Tiingo ETF proxies use daily log returns of `adjClose`.
- DEXUSEU uses daily log changes in the USD-per-EUR rate.
- DGS10 yield is converted to a 10-year semi-annual par-bond price return. With yield in decimal, `y = DGS10/100`, `Δy_t = y_t − y_(t−1)`, and `r_t = ln(1 − D·Δy_t)`. The as-of yield is `y* = 4% (0.04)`, fixed in advance as a modelling assumption; modified duration is `D = 8.1757` (modified duration of a 10-year semi-annual par bond at `y*`), using `D = (1/y*)·[1 − (1 + y*/2)^(−20)]`. The same 10-year duration is used for all rates products. Convexity, carry and roll-down are ignored.
- h-day log returns are overlapping sums of daily log returns; long loss is `−R_h`, short loss is `+R_h`. Both tails are measured.

Limitations: SPY is an index proxy and understates single-name risk, idiosyncratic jumps and swap basis; GLD is spot gold used for Brent, copper and natural-gas futures, without roll yield or contango; HYG mixes credit spreads, rate duration, carry and ETF/NAV dislocations; DEXUSEU stands in for other FX pairs and ignores forward points; DGS10 is a US 10-year par-bond proxy and is not maturity-matched to the 2Y/5Y futures or the sovereign products, whose currencies and maturities are unspecified. Within-type product, PB and tier relativities remain those of Phase 1.

### 2.4 Input digest and reproduction rule

The fetch utility writes one committed digest row per proxy with symbol, source, field, first/last date, row count, SHA-256 of canonical raw CSV (date and value at 10 decimals, LF line endings), SHA-256 of the canonical daily log-return series (12 decimals), and fetch date. On a clean clone: matching raw digests require byte-identical calibration CSVs; changed raw digests with return series matching within `1e-10` at every date require output agreement within `1e-9` relative; return differences beyond `1e-10` mean reproduction is not claimed and the differences are logged in `DEVIATIONS.md`. README wording must say reproduction is conditional on identical fetched data.

The committed digest identifies symbol and date range only; date-level differences are diagnosed against the author's local (git-ignored) raw copy.

## 3. Calibration method

For sample size `n`, sort losses descending as `L_(1) ≥ … ≥ L_(n)` and set `k = ceil((1−α)n)`. Empirical `ES_α` is the mean of the k largest losses; `VaR_α = L_(k)`. Both long- and short-side losses are calculated; the product type's measure is the larger side.

`ES_recent(d)` is ES 97.5 on overlapping h-day losses ending in `(d − 2 years, d]`. `ES_stress(d)` is the maximum ES 97.5 over every rolling window of 250 consecutive overlapping h-day losses ending on or before `d`. It uses only information available at `d` and is non-decreasing over time. The APC target is floored:

```text
T_t(d) = max(ES_recent(d), 0.75 × ES_recent(d) + 0.25 × ES_stress(d))
```

The floor prevents the weighted target falling below recent ES. `floor_binding` is true when `ES_stress < ES_recent`.

For each type, `R_t` is the equal-weighted mean of Phase 1 L1 `base_rate` over every product and PB row in that type. `b_t` is the Phase 1 volatility bucket of the proxy price index at as-of, using the existing 60-return rule and 0.10/0.20 cuts. For DGS10, the index is compounded from the §2.3 price returns starting at 100. The scalar is `k_t = T_t(as_of)/(vol_mult(b_t) × R_t)`. Each Phase 1 base-rate row for that product type is multiplied by `k_t`; product, PB and tier relativities are preserved. Financing spreads, phi, concentration terms, volatility multipliers and the 1.15 house buffer are unchanged; Phase 1 product volatility buckets stay in place. The equally weighted unit L1 margin across PBs and products at `b_t`, before buffer and concentration add-ons, equals `T_t`.

Outputs: `calibration_targets.csv` with target components and `calibrated_rates.csv` with one row per Phase 1 rate row.

## 4. Walk-forward backtest

For each proxy, estimation dates are its last trading day of each month from 2019-01 through 2026-09. Targets use only observations ending on or before the estimation date. Within the following calendar month, trading days are partitioned into consecutive, non-overlapping h-day blocks starting at day 1; incomplete leftover days are dropped, and no block crosses month-end. The first block return is the log price on its last day minus the log price on the estimation date.

For each side, an exceedance is a realized loss strictly above that date's target. APC and no-APC counts are reported separately; each side is tested against a nominal 1% exceedance probability under the stated ES 97.5 ≈ VaR 99 normality assumption. Report counts, observation counts, rates, Kupiec POF LR/p-value and a binomial traffic-light zone. For `X ~ Binomial(n, 0.01)`, green if `P(X≤x)<0.95`, yellow if `0.95≤P(X≤x)<0.9999`, red if `P(X≤x)≥0.9999`. Nothing is re-tuned after seeing the results.

## 5. Exchange-margin drivers

For IRSF/DGS10 at as-of, change one setting at a time: confidence level (ES 97.5 base, VaR 99, ES 99); MPOR (1, 2 base, 5 days); recent lookback (1, 2 base, 5 years); APC (none; base 25% stressed weight with floor; 1.25 × recent ES; or a 10-year ES floor); and overlapping h-day returns versus √h × one-day ES. Compare IRSF_10Y calibrated L1 pre-buffer unit margin at each PB with ZN initial margin as a percentage of notional, calculated from the recorded margin, settlement and multiplier. The 0.5–3× range is an expectation only; no proxy, parameter or duration is changed to meet it.

Outputs: `drivers_irsf.csv` and a bar chart in the separate calibration report.

## 6. Re-run on calibrated rates

On a copy of the loaded Phase 1 case, replace `base_rate` by calibrated rates joined on PB, product and tier. Re-run the existing optimiser, attribution and leave-one-out pass-through charge without reloading or changing the case on disk. If infeasible, record status and slack by block and continue. Write calibrated summary, PM charges and rank changes, PB moves, and binding limits/duals.

The new report is `reports/calib_42/report.html`, built by a separate function; Phase 1 `report.build` is unchanged. The CLI writes only under its `--out` directory. Phase 1 and Phase 2a output directories remain byte-identical.

## 7. Expected behaviour

Formula-implied properties are implementation checks: `T ≥ ES_recent`; ES 99 ≥ ES 97.5; every APC driver is at least the no-APC value; and APC exceedance counts cannot exceed no-APC counts for the same type, side and month.

Empirical expectations, reported as found: E-C1 the APC floor does not bind for any type at as-of; E-C2 target rises with MPOR, ES 97.5 ≥ VaR 99, and √h and overlapping estimates differ by less than 25%; E-C3 APC strictly lowers the worse-side backtest count for at least four of seven types; E-C4 at least one PM charge rank changes; E-C5 the IRSF_10Y calibrated pre-buffer margin/ZN initial margin ratio lies within 0.5–3× at every PB. No outcome is a calibration target.

## 8. Acceptance tests (C1–C13)

Tests C1–C5 are authored with the calibration core; C6–C13 cover pipeline, report, data and plumbing.

- C1: hand-worked 120-loss ES/VaR rule to `1e-12`; for n=40, k=1.
- C2: overlapping h-day return length and first value.
- C3: APC blend identity when the floor does not bind; floor value and binding flag when it does; `T ≥ ES_recent`.
- C4: the equal-weighted pre-buffer family margin across every product and PB at L1 equals `T`; IRSF_10Y buffered margin equals 1.15 times family margin.
- C5: every calibrated rate preserves its Phase 1 type scalar; 924 rows and no duplicate/lost keys.
- C6: Phase 1 summary totals match to cents; calibrate CLI leaves every file under `reports/run_42/` and `reports/stress_42/` byte-identical.
- C7: changing returns after date `d` cannot change targets at `d`; stress ES is non-decreasing over estimation dates.
- C8: calibrated PM pass-through charges sum to calibrated total margin.
- C9: 21-day month anchors h=10 and h=2 blocks as fixed in §4; no block crosses month-end.
- C10: binomial traffic-light boundaries at n=250 and Kupiec LR at x=0.
- C11: hand-worked DGS10 yield-to-price transform and duration formula.
- C12: ES 99 ≥ ES 97.5; each APC driver ≥ no APC; APC exceedances ≤ no-APC exceedances for every type, side and month.
- C13: fixed five-row input digest, rescaled-price tolerance case and changed-price non-reproduction case.

## 9. Out of scope and authorship boundary

Out of scope: actual provider house methodologies; exchange scanning-array models; inter-commodity or cross-type offsets; cross-PB netting; per-product calibration; Phase 2a re-run on calibrated rates; margin-call dynamics; real provider data; model validation. Phase 1 formulas, data and outputs remain unchanged.

The author writes the pre-registration, calibration core and C1–C5. AI-assisted work covers data fetch/digest, surrounding pipeline, CLI, separate report, plumbing and C6–C13. Any deviation is recorded before results are interpreted.

## 10. Claim rule (only after completion)

BUILD label only: calibrated per-product-type margin rates to illustrative public-market proxies (ES 97.5%, assumed MPORs by product type, point-in-time stressed-period weighting with a floor), with a walk-forward exceedance backtest; re-ran financing allocation and PM pass-through charge on calibrated rates. Never imply actual provider, Treasury or exchange calibration, or that the model is validated. State the authorship split when asked.
