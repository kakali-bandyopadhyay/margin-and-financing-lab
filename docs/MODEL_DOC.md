# Model documentation – margin-and-financing-lab Phase 1

## 0 Document control

| Field | Value |
|---|---|
| Version | 1.0 |
| Date | 18 November 2026 |
| Author | Kakali Bandyopadhyay |
| Model ID | `mfl-phase1` |
| Code commit | c927356 |
| Status line | Status: not validated (see §12) |

**Author's note:** Drafted with AI assistance; reviewed and edited by the author.

## 1 Purpose and intended use

This model compares ways to place a synthetic multi-asset portfolio across prime brokers (PBs). It selects the allocation with the lowest modelled financing and margin-funding cost over the chosen horizon while respecting PB capacity, counterparty limits and borrow availability. It also estimates the margin associated with each portfolio manager's (PM's) positions and applies an illustrative internal charge.

The intended audience is the treasury or financing desk exploring allocation trade-offs, with PMs as readers of their usage and charge summaries. Use the results only to understand the behaviour of this prototype under its stated inputs. They are not suitable for forecasting actual margin, negotiating with PBs, or capital and liquidity reporting. The boundary and original purpose are set out in the [pre-registration](../prereg/PREREGISTRATION.md#1-purpose-and-boundary).

## 2 Model overview and boundary

The calculation proceeds through three model modules and a reporting layer. M1 estimates margin for a given position allocation. M2 searches for a low-cost allocation subject to the stated operating limits. M3 attributes modelled margin to PMs and derives the illustrative charge. Reporting assembles the allocation, margin, constraints, attribution and sensitivity results. The connections are drawn in [`module_flow.svg`](diagrams/module_flow.svg).

This is a personal prototype built on synthetic inputs. Its margin calculation is a rate-based approximation, with simple offsets applied within a PB; it is neither a portfolio-margin engine nor calibrated to a PB, exchange or clearing house. The charge is an example policy. Outputs explain the consequences of the chosen assumptions and do not predict actual outcomes or represent any institution's methodology. The model has not been validated, and production use would require independent validation plus review by Treasury, Risk and Legal. See the [README boundary](../README.md).

## 3 Data

The loader reads nine CSV tables into DuckDB. The files are synthetic, and their sizes, origins and provenance labels are maintained in [SOURCES.md](../data/SOURCES.md).

| Table | Rows | Source file |
|---|---:|---|
| Portfolio managers | 10 | [`pms.csv`](../data/raw/pms.csv) |
| Issuers | 44 | [`issuers.csv`](../data/raw/issuers.csv) |
| Products | 77 | [`products.csv`](../data/raw/products.csv) |
| PB providers | 4 | [`providers.csv`](../data/raw/providers.csv) |
| Positions | 214 | [`positions.csv`](../data/raw/positions.csv) |
| PB/product rates | 924 | [`pb_rates.csv`](../data/raw/pb_rates.csv) |
| PB borrow terms | 176 | [`pb_borrow.csv`](../data/raw/pb_borrow.csv) |
| Price history | 9,669 | [`price_history.csv`](../data/raw/price_history.csv) |
| Model parameters | 14 | [`params.csv`](../data/raw/params.csv) |

At load, `io.py` checks that parameter names are complete and unique and that each value is in its permitted domain. It rejects non-positive base rates, φ outside [0, 1), θ outside (0, 1), negative c or liquidity premium, and any φ/θ/c mismatch between `params.csv` and its PB-level source file. It checks duplicate keys and requires a rate for every held product/tier at every PB. Product types must agree with their asset classes and issuer requirements; locate flags are restricted to product types that may require a locate; issuer references must exist; and only equity or credit issuers may be concentration-eligible. Position IDs and references must be valid, sides must be +1 or −1, notionals must be finite and positive, and liquidity tiers must be recognised. Held products need price history, and price-date keys must be unique. The loader also checks for a provenance tag on every source-table row and a tag for each parameter in SOURCES.md. Volatility buckets are derived from observed closes. The full input contract is in [pre-registration §2](../prereg/PREREGISTRATION.md#2-data-contract).

The [provenance register](../data/SOURCES.md) records the synthetic generators, checks, assumptions and later data revisions. Its revision log explains the redraws to rates, positions and provider limits. A7 is the only public comparison; its ZN margin and settlement snapshot is in [`exchange_margin.csv`](../data/public/exchange_margin.csv), with source details in SOURCES §4. That comparison is a scale check, not a rate-setting exercise.

## 4 Assumptions and parameters

The primary run uses the values below. Each is an assumption or a reproducibility setting; the rationale and source tags are recorded in [pre-registration §7](../prereg/PREREGISTRATION.md#7-parameters-fixed-for-the-primary-run) and [SOURCES §3](../data/SOURCES.md#3-model-parameters-datarawparamscsv).

| Input | Primary value | Tag | Rationale |
|---|---:|---|---|
| `as_of_date` | 2026-10-30 | Assumed | End date for the synthetic calendar |
| Horizon H | 90 days | Assumed | One-quarter comparison period |
| Liquidity premium ℓ | 100 bps | Assumed | Cost assigned to cash held as margin |
| House buffer | 1.15 | Assumed | Multiplier applied to modelled PB margin |
| `pass_through_bps` | 100 bps | Assumed | Matches the margin-funding premium |
| Offset fraction φ | 0.60 | Assumed | Share of family exposure treated as net |
| Concentration threshold θ | 0.25 | Assumed | PB gross share before issuer add-on (D2) |
| Concentration rate c | 0.02 | Assumed | Rate on issuer exposure above threshold |
| Volatility cut-offs | 10% / 20% | Assumed | Boundaries between V1, V2 and V3 (D1) |
| Volatility multipliers | 1.0 / 1.3 / 1.8 | Assumed | Multipliers for V1 / V2 / V3 (D1) |
| Random seed | 42 | Fixed | Makes seeded data and checks repeatable |

The design clarifications C1–C4 in [pre-registration §2](../prereg/PREREGISTRATION.md#2-data-contract) define where these terms apply. θ and c belong to each PB; φ belongs to each PB/product/tier rate. Only eligible corporate issuers receive a concentration add-on. Funding cost depends on whether a position is long or short and whether a short requires an available locate. A PM's solo margin uses that PM's positions at the optimal allocation, without reallocating the rest. D1 fixes absolute volatility thresholds; D2 measures concentration against the PB's own allocated gross.

## 5 Methodology

### 5.1 M1 – margin proxy

M1 groups positions by product, liquidity tier and volatility bucket. Within each PB and group, gross exposure adds allocated notionals; net exposure takes the absolute value of the signed allocated total. The group's rate is the applicable PB base rate scaled by its volatility multiplier. Before the house buffer, family margin is that rate times φ-weighted net exposure plus (1−φ)-weighted gross exposure.

For each eligible issuer, M1 adds c times the amount by which issuer gross exceeds θ times total gross at that PB, floored at zero. PB margin is the buffered sum of its family amounts and issuer add-ons; total M is the sum of PB margins. The implementation and its tested properties are described in [pre-registration §3](../prereg/PREREGISTRATION.md#3-m1--margin-proxy). After optimisation, the reported value is recalculated from the chosen allocation; solver epigraph values are not used as the reported margin.

### 5.2 M2 – allocation optimiser

M2 minimises financing expense plus the cost of funding modelled margin, expressed in USD for H days on an ACT/360 basis. The linear program enforces four blocks: complete nonnegative allocation of each position; PB gross below capacity; PB margin below its counterparty limit; and located short exposure below issuer/PB borrow availability, with no placement where a required locate is absent or unavailable. Epigraph variables represent absolute net exposure and positive-part concentration amounts.

The solver status is checked. If the original problem is infeasible, a penalised-slack solve identifies which constraint blocks prevent feasibility. Capacity, counterparty and borrow duals are diagnostic sensitivities; degeneracy can make them non-unique. Fixed charges, minimum balances and activation decisions are excluded because they require a mixed-integer model. The formal objective and constraints are in [pre-registration §4](../prereg/PREREGISTRATION.md#4-m2--allocation-optimiser).

### 5.3 M3 – usage attribution and charge

For the primary usage measure, M3 removes one PM's positions while holding the optimal allocation w* fixed, then compares the reduced-book margin with full-book margin. A PM's usage can be negative when that PM's positions reduce overall modelled margin. This attribution does not re-optimise the remaining positions.

The solo-margin amount for a PM is calculated on that PM's own positions at w*. M3 allocates the residual between total margin and summed usage in proportion to solo margins, then applies the pass-through rate and horizon factor to determine the illustrative charge. If the book is empty, all shares are zero; a zero solo-margin denominator in any other case is treated as an error. The re-optimised leave-one-out exhibit is reported separately and does not feed the charge. These definitions follow [pre-registration §5](../prereg/PREREGISTRATION.md#5-m3--pm-usage-and-illustrative-charge).

### 5.4 Exhibits

The report presents re-solved usage, all-in cost attribution and Euler allocations as distinct exhibits. For a convex degree-one homogeneous proxy, every subgradient sums to M. At a kink, the PM split is not unique, so the report gives a [low, high] range for each PM's Euler value. Aumann–Shapley equals Euler when the Euler allocation is unique, because the gradient is then constant along the ray; the model does not calculate Aumann–Shapley separately. This is the corrected statement recorded in [D-04](../prereg/DEVIATIONS.md#d-04--2026-11-18--m3-exhibits-tests-x1x3-added-euler-wording-corrected).

## 6 Implementation

| Component | Entry points | Responsibility |
|---|---|---|
| `src/mfl/margin.py` | `build_index`, `margin_by_pb`, `margin_detail` | Build reusable groupings; calculate PB margin and detailed components |
| `src/mfl/optimise.py` | `optimise` | Solve the allocation LP and return diagnostics |
| `src/mfl/attribution.py` | `attribute`, `pm_usage` | Calculate PM usage, residual allocation and charges |
| `src/mfl/exhibits.py` | `resolve_usage`, `all_in_cost`, `euler_allocation` | Produce separate allocation and margin exhibits |
| `src/mfl/io.py` | `load_case`, CSV writer | Load, validate and serialise case data |
| `src/mfl/report.py` | `build` | Create DuckDB report tables and the HTML report |
| `src/mfl/cli.py` | `run`, `main` | Coordinate a run and handle failure reporting |
| `sql/*.sql` | SQL views | Shape calculation outputs into report tables |

The package declares Python 3.11 or newer; the CI matrix exercises Python 3.11 and 3.14. Optimisation uses cvxpy with HiGHS, and DuckDB supplies the reporting views. CI installs the package, runs pytest and generates a seeded report. See the [source modules](../src/mfl/) and [CI workflow](../.github/workflows/ci.yml).

## 7 Conceptual soundness

The acceptance suite checks the implementation against hand calculations and mathematical or operational properties. The foundational tests were added before the corresponding model components, as shown by the commit sequence below and in [DEVIATIONS.md](../prereg/DEVIATIONS.md).

| Test group | What it checks | Test file |
|---|---|---|
| A1 | Hand calculation for margin, attribution and charge | [`test_a1_hand_worked.py`](../tests/acceptance/test_a1_hand_worked.py), [`HAND_WORKED_EXAMPLE.md`](HAND_WORKED_EXAMPLE.md) |
| A2a–g | Zero and nonnegative margin, monotonicity, convexity, homogeneity and determinism | [`test_a2_invariants.py`](../tests/acceptance/test_a2_invariants.py) |
| A3 | Margin reduction from the stated offset rule | [`test_a3_offset_credit.py`](../tests/acceptance/test_a3_offset_credit.py) |
| A4 | No offset between different PBs | [`test_a4_no_cross_pb_netting.py`](../tests/acceptance/test_a4_no_cross_pb_netting.py) |
| A5 | Constraint checks, infeasibility diagnosis and epigraph agreement | [`test_a5_constraints.py`](../tests/acceptance/test_a5_constraints.py) |
| A6a–c | Usage total, ordering, empty cases and invalid-rate rejection | [`test_a6_attribution.py`](../tests/acceptance/test_a6_attribution.py) |
| X1–X3 | Re-solve, all-in cost and Euler range exhibits | [`test_x_exhibits.py`](../tests/acceptance/test_x_exhibits.py) |
| A7 | Comparison with one published matched-product margin | [`test_a7_exchange_sanity.py`](../tests/acceptance/test_a7_exchange_sanity.py) |
| A8 | Required validation disclosure and heading sequence | [`test_a8_not_validated.py`](../tests/acceptance/test_a8_not_validated.py) |

The Git history shows the tests landing before their associated implementation: `10f7341` (A1–A4) precedes M1 `3fd132b`; `0774571` (A5) precedes M2 `14a1266`; `4fe56b2` (A6) precedes M3 `5ce9d22`; and `ed36c85` (X1–X3) precedes exhibits `0d204f3`.

## 8 Benchmarking (sanity only)

A7 compares `IRSF_10Y` with the CBOT ZN December 2026 front contract. For each PB it divides the model's `margin_by_pb` amount by notional and compares that percentage with exchange initial margin as a percentage of notional. The allowed proxy-to-exchange ratio was set to 0.5–4.0 before the CME value was checked. The test reads the non-HRP outright margin and same-day settlement recorded in [`exchange_margin.csv`](../data/public/exchange_margin.csv); PB-specific ratios are reported in [RESULTS.md §8](../RESULTS.md#8-exchange-margin-sanity-check-a7--sanity-only-not-calibration). The check screens for scale or unit mistakes; it is not calibration and does not change any rate. See [SOURCES §4](../data/SOURCES.md#4-public-sources-sanity-check-a7-only) and [D-06](../prereg/DEVIATIONS.md).

## 9 Outcomes analysis

There is no realised outcome series to compare with this model: the portfolio is synthetic, and it contains no historical PB margin statements or margin-call observations. Outcome analysis would require PB statements spanning time, a proxy-versus-actual comparison over different market conditions, and a record of overrides with their reasons. Until then, synthetic-run behaviour cannot establish forecasting performance.

## 10 Sensitivity analysis

The planned grid changes volatility buckets by one step, scales base rates by 1.25, tests θ at 0.20 and 0.30, and varies ℓ across 100, 300 and 500 basis points; the ℓ cases were added in D-01. Each scenario re-runs the optimiser. The final sensitivity grid is in [RESULTS.md §7](../RESULTS.md#7-sensitivity-grid-each-scenario-re-optimised), and the E1–E5 expected-behaviour assessment is in [RESULTS.md §9](../RESULTS.md#9-expected-behaviour-e1e5-prereg-9--confirmed--not-confirmed). See [pre-registration §§8–9](../prereg/PREREGISTRATION.md#8-outputs-reported-all-of-them-whatever-they-show).

## 11 Limitations

1. Margin is estimated with linear rates, not SPAN, TIMS or VaR portfolio margin; offsets are limited to one family at one PB.
2. Volatility classification uses absolute thresholds on 60 returns; asset-class variation is represented by base rates (D1).
3. Phase 1 assigns common φ, θ and c values across PBs, although the schema can represent PB-level differences (C1).
4. The calculation is static over one horizon: it has no intraday or path-dependent margin and no margin-call dynamics. Stress modelling is deferred to Phase 2.
5. Fixed fees, minimum balances and account activation are absent; adding them calls for a mixed-integer formulation.
6. Constraint duals indicate local sensitivities, but may not be unique when the solution is degenerate.
7. Euler allocations have no unique PM split at kinks. Final net and hinge counts should be read from [RESULTS.md](../RESULTS.md).
8. Borrow availability does not change over time; recall risk, collateral currencies, FX haircuts and inter-PB cross-margining are not modelled.
9. The inputs are synthetic, the charge rule is illustrative and outcome analysis cannot be performed without actual PB data.

## 12 Validation status

This model has not been independently validated and must not be used for decisions without independent validation and Treasury, Risk and Legal review.

Independent review should examine whether the model is fit for its intended use, whether its concepts and implementation are sound, whether the inputs and outputs are controlled, and whether performance can be assessed against actual PB observations. It should also challenge the assumptions, sensitivity behaviour, limitations, solver handling and reporting, with reviewers independent of development. Passing this project's tests does not provide that validation.

## 13 Use controls and monitoring (proposed)

For each run, first check that input validation completed and that the solver status is optimal. An infeasible result should be read with its status banner and slack-block diagnosis, not as a usable allocation. If this prototype were monitored over time, reviewers should track PB limit use, binding-constraint duals, kink counts and types, solver outcomes and slack diagnostics. The report's constraint and kink exhibits are tables 30 and 42; dual values are indicative and may not have a unique interpretation.

## 14 Change log

| Entry | Commit |
|---|---|
| D-01 – liquidity-premium sensitivity cases | [`bb729a9`](../prereg/DEVIATIONS.md) |
| D-02 – reusable margin index | [`8b3f4f5`](../prereg/DEVIATIONS.md) |
| D-03 – reject incomplete PM lists in usage | [`971fac2`](../prereg/DEVIATIONS.md) |
| D-04 – exhibit tests and corrected Euler explanation | [`ed36c85`](../prereg/DEVIATIONS.md) |
| D-05 – require complete PM coverage and check Euler total | [`e211dec`](../prereg/DEVIATIONS.md) |
| D-06 – matched-product A7 check | [`85147fd`](../prereg/DEVIATIONS.md) |
| Pre-registration | [`8f4dcbd`](../prereg/PREREGISTRATION.md) |
| D-07 – A8 document-control test | [`c927356`](../prereg/DEVIATIONS.md) |
| D-08 – input contract enforced at load | [`c927356`](../prereg/DEVIATIONS.md) |

## References

- Board of Governors of the Federal Reserve System, [SR 26-2: Revised Guidance on Model Risk Management](https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm), issued 17 April 2026 and superseding SR 11-7.
- Office of the Comptroller of the Currency, [OCC Bulletin 2026-13](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html), issued 17 April 2026 and replacing OCC 2011-12.
- CME Group, [10-Year T-Note Futures Margins](https://www.cmegroup.com/markets/interest-rates/us-treasury/10-year-us-treasury-note/margins); snapshot details are in [SOURCES §4](../data/SOURCES.md#4-public-sources-sanity-check-a7-only).
