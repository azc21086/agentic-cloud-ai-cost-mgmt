# GCSI experiment report

Config digest `9f7742784ad9`; prompt `decision_record_v1:566566f851bd5cbb`; model `gpt-4o-mini`; runs: 20 (4 families x 5 seeds).

> Delays and costs in the economics are assumptions (`EconomicsConfig`), not measurements. Intervals are 95%: Wilson for proportions, t for means over runs.

## E1. Detection

| Detector | Waste events detected | Incidents on a waste event (precision) | Incidents per run | Days from event start to alert | Benign surges flagged |
|---|---|---|---|---|---|
| Fixed-threshold alert | 100.0% [96.9, 100.0] (n=120) | 7.6% [6.5, 8.9] (n=1764) | 88.2 [53.7, 122.7] | 0.25 [0.09, 0.41] | 98.3% [91.1, 99.7] (n=60) |
| Forecast-residual alert | 85.8% [78.5, 91.0] (n=120) | 34.7% [29.5, 40.2] (n=300) | 15.0 [9.4, 20.6] | 1.51 [1.14, 1.88] | 71.7% [59.2, 81.5] (n=60) |

## E2. Decision outcomes by method

| Method | Waste incurred, USD/run | Human reviews or triages/run | Disruptive actions executed/run | Harmful automatic actions/run (disruptive or masking) | Wrong-auto rate | Total cost J, USD/run |
|---|---|---|---|---|---|---|
| Fixed-threshold alert (human triage) | 9731 [7904, 11558] | 88.2 [53.7, 122.7] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | n/a (no autonomous action) | 14141 [11535, 16747] |
| Forecast-residual alert (human triage) | 12997 [9575, 16420] | 15.0 [9.4, 20.6] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | n/a (no autonomous action) | 13747 [10355, 17140] |
| Agent, ungoverned (executes every proposal) | 12806 [9270, 16343] | 0.0 [0.0, 0.0] | 6.70 [3.50, 9.90] | 6.95 [3.59, 10.31] | 46.3% [40.8, 52.0] (n=300) | 26206 [18032, 34381] |
| Agent, governed (validation + routing rule) | 9940 [7056, 12825] | 12.3 [7.4, 17.2] | 0.00 [0.00, 0.00] | 0.10 [-0.04, 0.24] | 3.7% [1.0, 12.5] (n=54) | 10569 [7640, 13497] |

Paired difference in total cost J per run (negative favours the governed agent): vs ungoverned -15638 [-22599, -8676]; vs residual alert -3179 [-4737, -1621]; vs threshold alert -3572 [-5577, -1568] USD.

## E3. Governance layer behaviour

| Measure | Value |
|---|---|
| Decisions evaluated | 300 |
| Schema and business-rule valid | 97.3% [94.8, 98.6] (n=300) |
| Routed AUTO | 18.0% [14.1, 22.7] (n=300) |
| Routed REVIEW | 79.3% [74.4, 83.5] (n=300) |
| Routed REJECT | 2.7% [1.4, 5.2] (n=300) |
| Action matches ground truth (valid records) | 50.7% [45.0, 56.4] (n=292) |
| Brier score of final confidence (valid records) | 0.284 |
| Repeat-run agreement | 72.0% [66.7, 76.8] (n=300) |
| Material-autonomy violations (property i; must be 0) | 0 |
| Mean latency per decision, s | 2.49 |
| Mean tokens per decision (in/out) | 758 / 205 |

## E4. Total cost J by scenario family (USD per run)

| Family | Fixed-threshold alert | Forecast-residual alert | Agent, ungoverned | Agent, governed |
|---|---|---|---|---|
| growth | 11405 [7075, 15736] | 12048 [5965, 18130] | 18915 [6814, 31016] | 8151 [4415, 11886] |
| lumpy | 17368 [13150, 21585] | 13260 [7815, 18706] | 50209 [34504, 65914] | 12971 [7314, 18628] |
| steady | 8820 [4852, 12787] | 10233 [4889, 15576] | 13625 [1832, 25418] | 7099 [4058, 10141] |
| volatile | 18972 [12591, 25353] | 19449 [5412, 33487] | 22077 [9776, 34378] | 14054 [1306, 26802] |

## E5. Sensitivity to human delays (mean difference in J, USD per run)

| human_triage_days | review_days | governed minus residual alert | governed minus ungoverned |
|---|---|---|---|
| 1.0 | 0.5 | -293.0 | -14194.0 |
| 1.0 | 1.0 | 560.0 | -13341.0 |
| 1.0 | 2.0 | 2387.0 | -11514.0 |
| 3.0 | 0.5 | -4032.0 | -16491.0 |
| 3.0 | 1.0 | -3179.0 | -15638.0 |
| 3.0 | 2.0 | -1352.0 | -13811.0 |
| 5.0 | 0.5 | -8083.0 | -18817.0 |
| 5.0 | 1.0 | -7230.0 | -17964.0 |
| 5.0 | 2.0 | -5403.0 | -16137.0 |
| 7.0 | 0.5 | -11290.0 | -20999.0 |
| 7.0 | 1.0 | -10437.0 | -20146.0 |
| 7.0 | 2.0 | -8610.0 | -18319.0 |

## E6. Policy sweep: thresholds tau_c and tau_I (governed agent)

| tau_conf | tau_impact | auto share | wrong-auto rate | mean J, USD/run |
|---|---|---|---|---|
| 0.6 | 1000.0 | 15.0% | 4.4% | 10541.0 |
| 0.6 | 2500.0 | 19.3% | 3.4% | 10512.0 |
| 0.6 | 5000.0 | 20.3% | 3.3% | 10553.0 |
| 0.6 | 10000.0 | 20.3% | 3.3% | 10553.0 |
| 0.7 | 1000.0 | 14.7% | 4.5% | 10543.0 |
| 0.7 | 2500.0 | 19.0% | 3.5% | 10514.0 |
| 0.7 | 5000.0 | 20.0% | 3.3% | 10555.0 |
| 0.7 | 10000.0 | 20.0% | 3.3% | 10555.0 |
| 0.8 | 1000.0 | 12.7% | 5.3% | 10557.0 |
| 0.8 | 2500.0 | 17.0% | 3.9% | 10528.0 |
| 0.8 | 5000.0 | 18.0% | 3.7% | 10569.0 |
| 0.8 | 10000.0 | 18.0% | 3.7% | 10569.0 |
| 0.9 | 1000.0 | 9.3% | 7.1% | 10579.0 |
| 0.9 | 2500.0 | 12.3% | 5.4% | 10559.0 |
| 0.9 | 5000.0 | 12.7% | 5.3% | 10557.0 |
| 0.9 | 10000.0 | 12.7% | 5.3% | 10557.0 |