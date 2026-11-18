# margin-and-financing-lab

**Boundary.** This is a personal build on synthetic data. It is not a portfolio-margin model and is not calibrated to any prime broker, exchange or clearing house: the margin proxy uses stated rates, volatility buckets and a simple per-broker offset rule, so offsets are approximated. The internal charge policy is illustrative. Outputs describe how the model behaves under its stated assumptions; they are not predictions, not any firm's methodology, and the model is not validated. Any production use would need independent model validation and Treasury, Risk and Legal review.

## What it does
Allocates a synthetic multi-asset hedge-fund book across synthetic prime brokers at minimum financing-plus-margin-funding cost over a stated horizon, subject to capacity, counterparty and borrow limits, then attributes margin usage and an illustrative charge to portfolio managers.

## Status
Pre-registration stage – see `prereg/PREREGISTRATION.md`. Model code follows once it is committed.
