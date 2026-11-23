# Hand-worked example – margin-and-financing-lab (Phase 1 and Phase 2a)

This example hand-traces the two fixed allocations in §6.1 of `prereg/PREREGISTRATION.md`. It is an arithmetic check of the margin and attribution rules; the stated placements define w for each case. Amounts are USD. The concentration threshold is recomputed from the gross that remains at each PB for the full book, each leave-one-out book, and each PM's solo margin.

Toy numbers chosen for hand calculation; not market or provider data.

## Inputs and formulas

- Buffer = 1.15; offset share φ = 0.60; concentration threshold θ = 0.25; concentration rate c = 0.02.
- Equity family is L1/V3, so its volatility multiplier is 1.8. Govt-bond family is L1/V1, so its multiplier is 1.0.
- Rates: equity X = 0.15 × 1.8 = 0.27; equity Y = 0.18 × 1.8 = 0.324; govt bond X = 0.02; govt bond Y = 0.015.
- `FM = r × [φ × net + (1−φ) × gross]`; `net = |signed notional|` within each product/tier/volatility family and PB.
- `add-on = c × max(0, issuer gross − θ × PB gross)`, for the conc-eligible corporate equity issuer only. The sovereign govt bond contributes to PB gross but has no issuer add-on.
- `M(PB) = 1.15 × (sum of family FM + sum of issuer add-ons)`; total `M` is the sum over PBs.
- Usage `u_k = M(full book) − M(book with PM k removed)`. Solo margin keeps that PM's positions at the stated allocation. Charge allocation is `u_k + share_k × R`; charge factor is `100 bps × 90/360 = 0.0025`.

## Case (a): all positions at X

### Full book

At X, gross is 36,000,000: equity gross 16,000,000 (P1 long 10,000,000 and P2 short 6,000,000) plus sovereign bond gross 20,000,000. Signed equity net is `|10,000,000 − 6,000,000| = 4,000,000`.

| PB | Family | Gross | Net | r | FM |
|---|---|---:|---:|---:|---:|
| X | Equity L1/V3 | 16,000,000 | 4,000,000 | 0.27 | 2,376,000 |
| X | Govt bond L1/V1 | 20,000,000 | 20,000,000 | 0.02 | 400,000 |
| Y | No positions | 0 | 0 | — | 0 |

Equity FM calculation: `0.27 × (0.60 × 4,000,000 + 0.40 × 16,000,000) = 2,376,000`.

| PB | Eligible issuer gross G(g,p) | PB gross G(p) | Threshold θ × G(p) | Add-on |
|---|---:|---:|---:|---:|
| X | I1: 16,000,000 | 36,000,000 | 9,000,000 | `0.02 × (16,000,000 − 9,000,000) = 140,000` |
| Y | 0 | 0 | 0 | 0 |

`M(X) = 1.15 × (2,376,000 + 400,000 + 140,000) = 3,353,400`; `M(Y) = 0`; therefore `M = 3,353,400`.

### Leave-one-out and solo books

| Book | PB gross | Family gross / net; r; FM | Eligible issuer G(g,p); θ × G(p); add-on | M(PB) |
|---|---:|---|---|---:|
| Remove PM A (P2 remains) | X: 6,000,000 | Equity: 6,000,000 / 6,000,000; 0.27; 1,620,000 | I1: 6,000,000; 1,500,000; 90,000 | 1,966,500 |
| Remove PM B (P1 and P3 remain) | X: 30,000,000 | Equity: 10,000,000 / 10,000,000; 0.27; 2,700,000; govt bond: 20,000,000 / 20,000,000; 0.02; 400,000 | I1: 10,000,000; 7,500,000; 50,000 | 3,622,500 |
| PM A solo (P1 and P3) | X: 30,000,000 | Same as “Remove PM B” | Same as “Remove PM B” | 3,622,500 |
| PM B solo (P2) | X: 6,000,000 | Same as “Remove PM A” | Same as “Remove PM A” | 1,966,500 |

For “Remove PM B” and PM A solo, the sovereign bond counts in PB gross: `G(X) = 30,000,000`, so I1's threshold is 7,500,000 and its add-on is 50,000.

- `u_A = 3,353,400 − 1,966,500 = 1,386,900`.
- `u_B = 3,353,400 − 3,622,500 = −269,100`.
- `M_A^solo = 3,622,500`; `M_B^solo = 1,966,500`; solo-margin sum = 5,589,000.
- `R = 3,353,400 − 1,386,900 − (−269,100) = 2,235,600`.
- Shares: A = `3,622,500 / 5,589,000 = 35/54`; B = `1,966,500 / 5,589,000 = 19/54`.
- Allocated margin: A = `1,386,900 + (35/54 × 2,235,600) = 2,835,900`; B = `−269,100 + (19/54 × 2,235,600) = 517,500`.
- Charges: A = `2,835,900 × 0.0025 = 7,089.75`; B = `517,500 × 0.0025 = 1,293.75`. Total = 8,383.50 = `M × 0.0025`.

## Case (b): P1 at X; P2 and P3 at Y

### Full book

At X, gross is 10,000,000, all equity. At Y, gross is 26,000,000: short equity 6,000,000 plus sovereign bond 20,000,000.

| PB | Family | Gross | Net | r | FM |
|---|---|---:|---:|---:|---:|
| X | Equity L1/V3 (P1) | 10,000,000 | 10,000,000 | 0.27 | 2,700,000 |
| Y | Equity L1/V3 (P2) | 6,000,000 | 6,000,000 | 0.324 | 1,944,000 |
| Y | Govt bond L1/V1 (P3) | 20,000,000 | 20,000,000 | 0.015 | 300,000 |

| PB | Eligible issuer gross G(g,p) | PB gross G(p) | Threshold θ × G(p) | Add-on |
|---|---:|---:|---:|---:|
| X | I1: 10,000,000 | 10,000,000 | 2,500,000 | `0.02 × (10,000,000 − 2,500,000) = 150,000` |
| Y | I1: 6,000,000 | 26,000,000 | 6,500,000 | 0 (issuer gross is below threshold) |

`M(X) = 1.15 × (2,700,000 + 150,000) = 3,277,500`.

`M(Y) = 1.15 × (1,944,000 + 300,000 + 0) = 2,580,600`.

`M = 3,277,500 + 2,580,600 = 5,858,100`.

### Leave-one-out and solo books

| Book | PB gross | Family gross / net; r; FM | Eligible issuer G(g,p); θ × G(p); add-on | M(PB) |
|---|---:|---|---|---:|
| Remove PM A (P2 remains) | Y: 6,000,000 | Equity: 6,000,000 / 6,000,000; 0.324; 1,944,000 | I1: 6,000,000; 1,500,000; 90,000 | 2,339,100 |
| Remove PM B (P1 and P3 remain) | X: 10,000,000; Y: 20,000,000 | X equity: 10,000,000 / 10,000,000; 0.27; 2,700,000; Y govt bond: 20,000,000 / 20,000,000; 0.015; 300,000 | X I1: 10,000,000; 2,500,000; 150,000; Y: no eligible issuer | X: 3,277,500; Y: 345,000; total: 3,622,500 |
| PM A solo (P1 and P3) | X: 10,000,000; Y: 20,000,000 | Same as “Remove PM B” | Same as “Remove PM B” | 3,622,500 |
| PM B solo (P2) | Y: 6,000,000 | Same as “Remove PM A” | Same as “Remove PM A” | 2,339,100 |

- `u_A = 5,858,100 − 2,339,100 = 3,519,000`.
- `u_B = 5,858,100 − 3,622,500 = 2,235,600`.
- `M_A^solo = 3,622,500`; `M_B^solo = 2,339,100`; solo-margin sum = 5,961,600.
- `R = 5,858,100 − 3,519,000 − 2,235,600 = 103,500`.
- Shares: A = `3,622,500 / 5,961,600 = 0.6076388889`; B = `2,339,100 / 5,961,600 = 0.3923611111`.
- Allocated margin: A = `3,519,000 + (0.607638888888… × 103,500) = 3,581,890.625`; B = `2,235,600 + (0.392361111111… × 103,500) = 2,276,209.375`.
- Charges: A = `3,581,890.625 × 0.0025 = 8,954.7265625` → **8,954.73**; B = `2,276,209.375 × 0.0025 = 5,690.5234375` → **5,690.52**. Rounded charges total 14,645.25 = `M × 0.0025`.

## Phase 2a: stress add-on checks

This section hand-checks the fixed transforms and fixed-allocation identities in `prereg/PREREGISTRATION_PHASE2A.md`. It is an arithmetic check, not a results section; the stress results are reported in `RESULTS.md`. The numbers below are from the primary case (seed 42, `as_of_date` 2026-10-30); the bucket facts and §7 facts are asserted by `tests/acceptance/test_stress.py`, and the fixed-allocation and netting identities are checked there.

### Volatility re-bucketing (ST1a, ST1b)

Phase 1 derives a product's bucket with `margin.vol_bucket`: the last 60 close-to-close log returns through `as_of_date`, sample standard deviation (`ddof=1`), annualised by `sqrt(252)`, then cut at 0.10 / 0.20. ST1a multiplies that annualised vol by 2 and re-buckets with the same cuts; ST1b uses 1.5. A product with fewer than 60 usable returns remains V3.

For the two hand-worked products the return window is 2026-08-10 to 2026-10-30 (60 returns):

| Product | Phase 1 vol | Phase 1 bucket | ×2 vol | ST1a bucket | ×1.5 vol | ST1b bucket |
|---|---:|---|---:|---|---:|---|
| `CDS_ISS003` | 0.090769468946 | V1 | 0.181538937892 | V2 | 0.136154203419 | V2 |
| `CE_ISS008` | 0.193704438203 | V2 | 0.387408876406 | V3 | 0.290556657304 | V3 |

- `CDS_ISS003`: `0.090769 < 0.10` → V1; `×2 = 0.181539`, which is between 0.10 and 0.20 inclusive → V2; `×1.5 = 0.136154` → V2.
- `CE_ISS008`: `0.193704` is between 0.10 and 0.20 inclusive → V2; `×2 = 0.387409 > 0.20` → V3; `×1.5 = 0.290557 > 0.20` → V3.
- Across all 73 held products, ST1a moves 27 (9 V1→V2 and 18 V2→V3) and leaves 42 at V3; ST1b moves 22.

### ST2a fixed-allocation scaling (S3)

The uniform rate shock multiplies every `base_rate` by 1.5. At the fixed ST0 allocation `w0`, each family's `r = base_rate × vol_multiplier` scales by 1.5, so `FM` scales by 1.5. The concentration add-on does not: it uses `conc_rate`, not `base_rate`.

PB_B is the only primary-case PB with a non-zero concentration add-on, so it is the clean counter-example to “total margin scales by 1.5”:

| PB_B quantity | ST0 at `w0` | ST2a at `w0` |
|---|---:|---:|
| Family margin `FM` | 183,908,280.616502 | 275,862,420.924753 |
| Concentration add-on | 205,101.122628 | 205,101.122628 |
| `M = 1.15 × (FM + add-on)` | 211,730,389.000000 | 317,477,650.354489 |

`FM` scales exactly: `1.5 × 183,908,280.616502 = 275,862,420.924753`. The add-on is unchanged, so total margin is not `1.5 × 211,730,389.000000 = 317,595,583.500000`; it is lower by `1.15 × 0.5 × 205,101.122628 = 117,933.145511`. At a PB with no add-on, such as PB_A, total margin does scale exactly: `1.5 × 477,120,106.135151 = 715,680,159.202727`.

### ST2b fixed-allocation scaling (S4)

The two shocked PBs are the ST0 top two by allocated margin: PB_D (`764,910,552.835689`) and PB_A (`477,120,106.135151`). At `w0`, only those two PBs' family margins scale; the other two are unchanged.

| PB | Role | `FM` at `w0` | `M` at `w0` | ST2b `FM` | ST2b `M` |
|---|---|---:|---:|---:|---:|
| PB_A | shocked | 414,887,048.813175 | 477,120,106.135151 | 622,330,573.219762 | 715,680,159.202727 |
| PB_B | unshocked | 183,908,280.616502 | 211,730,389.000000 | 183,908,280.616502 | 211,730,389.000000 |
| PB_C | unshocked | 255,591,140.428239 | 293,929,811.492475 | 255,591,140.428239 | 293,929,811.492475 |
| PB_D | shocked | 665,139,611.161469 | 764,910,552.835689 | 997,709,416.742204 | 1,147,365,829.253534 |

For the shocked PBs, `FM_ST2b = 1.5 × FM_ST0`; for the unshocked PBs it is unchanged. PB_B's add-on (205,101.122628) is unchanged, as it must be because `conc_rate`, issuer gross and PB gross are unchanged at fixed allocation.

### ST3 netting decomposition (S7)

The ST3 run is infeasible (counterparty and borrow slack), so the allocation `w3` used below is the minimum-total-slack allocation returned by the Phase 1 slack re-solve. The netting arithmetic is still evaluated on that allocation.

For each PB, with the ST3 allocation `w3`:

```
M_with(p)    = 1.15 × ( Σ_f r(f,p) × [φ × net(f,p) + (1−φ) × gross(f,p)] + add-on(p) )
M_without(p) = 1.15 × ( Σ_f r(f,p) × gross(f,p) + add-on(p) )
NB(p)        = M_without(p) − M_with(p) ≥ 0
```

`M_without` sets `net = gross` for every family, i.e. treats each position as its own family. The concentration add-on is gross-based and side-blind, so it is identical in both and is not part of the netting effect. The same two quantities at ST0 give `NB0(p)`. Then:

```
netting_change(p) = NB0(p) − NB(p)          # positive = netting benefit lost
reallocation(p)   = M_without(p) − M_without0(p)
delta_vs_st0(p)   = M_with(p) − M0(p) = reallocation(p) + netting_change(p)
```

Worked PB_B row:

- ST3: `M_with = 623,239,932.663198`; `M_without = 790,059,053.083510`; `NB = 166,819,120.420311`.
- ST0: `M0 = 211,730,389.000000`; `M_without0 = 411,064,677.001378`; `NB0 = 199,334,288.001378`.
- `netting_change = 199,334,288.001378 − 166,819,120.420311 = 32,515,167.581067`.
- `reallocation = 790,059,053.083510 − 411,064,677.001378 = 378,994,376.082131`.
- `delta = 623,239,932.663198 − 211,730,389.000000 = 411,509,543.663198`.
- Check: `378,994,376.082131 + 32,515,167.581067 = 411,509,543.663198`.

The terminated PB_D row shows the loss directly: its ST0 `NB0 = 79,493,907.249908` becomes zero at ST3, so `netting_change = +79,493,907.249908`, `reallocation = −844,404,460.085597`, and `delta = −764,910,552.835689`.

For the total:

| Quantity | ST0 | ST3 |
|---|---:|---:|
| `M_with` | 1,747,690,859.463315 | 1,794,630,573.663198 |
| `M_without` | 2,275,466,684.343585 | 2,345,853,537.915310 |
| Netting benefit `NB` | 527,775,824.880269 | 551,222,964.252112 |
| `netting_change` | — | −23,447,139.371843 |
| `reallocation` | — | 70,386,853.571726 |
| `delta` | — | 46,939,714.199883 |

The identity holds: `70,386,853.571726 − 23,447,139.371843 = 46,939,714.199883`. The total netting change is negative on this run (netting benefit rose on reallocation), so E-S4 (“netting loss”) is **not met**; this is reported as found.

### ST3 terms

PB_D is the terminated PB: `notice_days = 126`, `nav_trigger_pct = 29.1`, termination date `2026-10-30 + 126 days = 2027-03-05`. At ST0, `2,912,025,250.53` of allocated notional sits at PB_D across 106 positions; that is the notional to re-place. The ST3/ST4 cost window starts at 2027-03-05 and remains 90 days long. PB_D is removed from the feasible set, so no position remains there; the two ISS010 shorts that had a locate only at PB_D become borrow slack (`POS0076`, `POS0098`).

## Phase 2b – C11 DGS10 transform

Use the hand-worked test yield series `DGS10 = [4.00%, 4.10%, 3.90%]` and the stated as-of test yield `y* = 0.04`. The modified duration of a 10-year semi-annual par bond is:

```text
D = (1 / 0.04) × [1 − (1 + 0.04 / 2)^(-20)]
  = 8.1757166723 years
```

Convert the daily changes in percentage points to decimal yields before applying the duration. The changes are `Δy_1 = +0.001` and `Δy_2 = −0.002`:

```text
r_1 = ln(1 − 8.1757166723 × 0.001) = −0.0082093211295
r_2 = ln(1 − 8.1757166723 × (−0.002)) = +0.0162191883083
```

The test compares both returns and the duration calculation with the implementation to absolute tolerance `1e-12`.

## Phase 2b – C9 window anchoring

Let the estimation date be 31 January and the next month contain 21 trading-day observations. Starting with `P(d_m) = 100`, take each following close to be `100 × exp(0.01j)` on day `j`. For `h = 10`, the first window is days 1–10 and its return is `ln(P(day 10)) − ln(P(d_m)) = 0.10`; a second window uses days 11–20, and day 21 is dropped. For `h = 2`, ten complete windows use days 1–20 and day 21 is dropped. Each window starts immediately after the previous one, and no window crosses the month-end.

