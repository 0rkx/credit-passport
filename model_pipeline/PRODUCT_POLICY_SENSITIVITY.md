# Product policy sensitivity

This is an internal scorecard-policy check. It does not train a model, read a
repayment label, or claim outcome calibration.

The reproducible script is
`model_pipeline/scripts/analyze_product_policies.py`. It reuses the pipeline's
correlated seven-domain population (`12,000` rows, fixed seed `20260920`),
replaces an unavailable domain with the scorecard neutral value `50`, and
expands the observed profile spread by `1.80x` around `50` so the configured
red/amber/green thresholds are exercised. This widened population is for
policy sensitivity only; it is not a training or underwriting cohort.

The score bands use the displayed integer score: red `<60`, amber `60–74`,
green `>=75`. The full machine-readable output is
`model_pipeline/product_policy_sensitivity.json`.

## Candidate comparison

The score vector order is commitment, income, capacity, liquidity, shock,
momentum, cross-border robustness. The selected policy is `selected-v2`.

| Candidate | Personal vs card integer difference | Personal vs student integer difference | Card vs student integer difference | Reason |
|---|---:|---:|---:|---|
| `v1` | 83.18% | 92.59% | 93.23% | The old policy often collapsed personal and card after rounding; average absolute difference was only 1.84 points. |
| `selected-v2` | **94.23%** | **91.28%** | **94.53%** | Distinguishes product purpose while keeping every domain present and avoiding a single-domain override. |
| `separation-heavy` | 95.60% | 91.87% | 95.58% | More separation, but its 40% card commitment and 30% personal income/capacity emphasis is less balanced for a general passport. |

## Selected policy distribution

All values below are from `12,000` bounded profiles. Mean, standard deviation
and percentiles are on the unrounded score; band percentages use the displayed
integer score.

| Product | n | Mean | SD | P10 | P25 | P50 | P75 | P90 | Red | Amber | Green |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Credit card | 12,000 | 51.473 | 18.352 | 27.312 | 38.598 | 51.503 | 64.463 | 75.559 | 65.84% | 22.98% | 11.18% |
| Personal loan | 12,000 | 51.457 | 18.746 | 26.548 | 38.247 | 51.488 | 65.049 | 76.356 | 65.55% | 22.47% | 11.98% |
| Student loan | 12,000 | 51.649 | 17.327 | 28.880 | 39.299 | 51.710 | 63.984 | 74.470 | 66.61% | 23.43% | 9.96% |

The source population is centered near 50, so red is intentionally the largest
review band. The sensitivity run still exercises all three bands, has nearly
the full 0–100 integer range, and has negligible floor/ceiling clipping. A
weight change should not be used to manufacture a target green rate.

## Monotonicity and score separation

The selected weights are all non-negative and sum to 100. Increasing any one
domain by one point never lowered the displayed score in the population:

| Product | Monotonicity pass rate |
|---|---:|
| Credit card | 100.00% |
| Personal loan | 100.00% |
| Student loan | 100.00% |

After integer rounding, selected-v2 produces a different score for:

| Pair | Different integer score | Mean absolute difference | Difference of at least 3 points |
|---|---:|---:|---:|
| Personal loan / credit card | 94.23% | 5.533 | 72.04% |
| Personal loan / student loan | 91.28% | 3.510 | 57.48% |
| Credit card / student loan | 94.53% | 5.672 | 72.78% |

## Selected weights

| Product | Commitment | Income | Capacity | Liquidity | Shock | Momentum | Cross-border | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Credit card | 35% | 10% | 15% | 25% | 5% | 5% | 5% | 100% |
| Personal loan | 20% | 25% | 30% | 10% | 5% | 5% | 5% | 100% |
| Student loan | 15% | 15% | 25% | 10% | 15% | 10% | 10% | 100% |

Credit card therefore prioritises payment history and cash buffer; a personal
loan prioritises observed income and room for a fixed instalment; a student loan
puts more weight on current affordability and resilience than on long payment
history. Momentum is observed income direction only, never projected graduate
earnings.
