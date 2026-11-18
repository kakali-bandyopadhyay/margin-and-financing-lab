# Hand-worked example – margin-and-financing-lab Phase 1

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
