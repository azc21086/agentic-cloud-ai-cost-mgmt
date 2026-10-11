# GCSI experiment report

Config digest `e408834b1b34`; prompt `decision_record_v1:566566f851bd5cbb`; model `mock-reasoner-v1`; runs: 80 (4 families x 20 seeds).

> **Mock reasoning layer.** The model here is a rule-based stand-in with deliberately injected faults (rate 15%). These results describe the pipeline under assumed failure rates and must not be reported as the performance of any language model.

> Delays and costs in the economics are assumptions (`EconomicsConfig`), not measurements. Intervals are 95%: Wilson for proportions, t for means over runs.

## E1. Detection

| Detector | Waste events detected | Incidents on a waste event (precision) | Incidents per run | Days from event start to alert | Benign surges flagged |
|---|---|---|---|---|---|
| Fixed-threshold alert | 100.0% [99.2, 100.0] (n=480) | 7.6% [7.0, 8.2] (n=7299) | 91.2 [74.7, 107.8] | 0.31 [0.24, 0.39] | 99.2% [97.0, 99.8] (n=240) |
| Forecast-residual alert | 86.5% [83.1, 89.2] (n=480) | 36.7% [34.0, 39.5] (n=1169) | 14.6 [12.1, 17.2] | 1.64 [1.44, 1.84] | 71.7% [65.7, 77.0] (n=240) |

## E2. Decision outcomes by method

| Method | Waste incurred, USD/run | Human reviews or triages/run | Wrong actions executed/run | Wrong-auto rate | Total cost J, USD/run |
|---|---|---|---|---|---|
| Fixed-threshold alert (human triage) | 9082 [8307, 9857] | 91.2 [74.7, 107.8] | 0.00 [0.00, 0.00] | n/a (no autonomous action) | 13644 [12550, 14738] |
| Forecast-residual alert (human triage) | 11694 [10496, 12893] | 14.6 [12.1, 17.2] | 0.00 [0.00, 0.00] | n/a (no autonomous action) | 12425 [11247, 13603] |
| Agent, ungoverned (executes every proposal) | 8766 [7577, 9956] | 1.0 [0.7, 1.2] | 4.81 [3.39, 6.23] | 37.8% [35.0, 40.7] (n=1092) | 18439 [14946, 21933] |
| Agent, governed (validation + routing rule) | 9476 [8372, 10580] | 11.7 [9.6, 13.8] | 0.00 [0.00, 0.00] | 6.0% [3.6, 9.8] (n=234) | 10075 [8953, 11197] |

Paired difference in total cost J per run (negative favours the governed agent): vs ungoverned -8365 [-11495, -5234]; vs residual alert -2350 [-3172, -1528]; vs threshold alert -3569 [-4388, -2750] USD.

## E3. Governance layer behaviour

| Measure | Value |
|---|---|
| Decisions evaluated | 1169 |
| Schema and business-rule valid | 88.4% [86.4, 90.1] (n=1169) |
| Routed AUTO | 20.0% [17.8, 22.4] (n=1169) |
| Routed REVIEW | 68.3% [65.6, 71.0] (n=1169) |
| Routed REJECT | 11.6% [9.9, 13.6] (n=1169) |
| Action matches ground truth (valid records) | 61.8% [58.8, 64.7] (n=1033) |
| Brier score of final confidence (valid records) | 0.207 |
| Repeat-run agreement | 100.0% [99.7, 100.0] (n=1169) |
| Material-autonomy violations (property i; must be 0) | 0 |
| Mean latency per decision, s | 0.00 |
| Mean tokens per decision (in/out) | 0 / 0 |

Injected faults by routing outcome (governed agent):

| Injected fault | AUTO | REVIEW | REJECT | Harmful action auto-executed |
|---|---|---|---|---|
| impact_distorted | 0 | 0 | 34 | 0 |
| invalid_json | 0 | 0 | 38 | 0 |
| missing_field | 0 | 0 | 35 | 0 |
| overconfident_misdiagnosis | 0 | 31 | 0 | 0 |
| unknown_action | 0 | 0 | 29 | 0 |
| unsupported_factor | 3 | 34 | 0 | 0 |

## E4. Total cost J by scenario family (USD per run)

| Family | Fixed-threshold alert | Forecast-residual alert | Agent, ungoverned | Agent, governed |
|---|---|---|---|---|
| growth | 10942 [8774, 13111] | 11820 [9295, 14344] | 11219 [8521, 13918] | 8609 [6646, 10571] |
| lumpy | 17461 [16180, 18743] | 11439 [9492, 13387] | 41877 [35983, 47771] | 12028 [9376, 14680] |
| steady | 9423 [8035, 10810] | 10906 [9240, 12573] | 7899 [6228, 9569] | 7735 [6474, 8995] |
| volatile | 16749 [15206, 18291] | 15535 [12451, 18618] | 12763 [9954, 15572] | 11928 [9235, 14621] |

## E5. Sensitivity to human delays (mean difference in J, USD per run)

| human_triage_days | review_days | governed minus residual alert | governed minus ungoverned |
|---|---|---|---|
| 1.0 | 0.5 | 38.0 | -9191.0 |
| 1.0 | 1.0 | 741.0 | -8488.0 |
| 1.0 | 2.0 | 2249.0 | -6980.0 |
| 3.0 | 0.5 | -3053.0 | -9067.0 |
| 3.0 | 1.0 | -2350.0 | -8365.0 |
| 3.0 | 2.0 | -842.0 | -6856.0 |
| 5.0 | 0.5 | -6448.0 | -8943.0 |
| 5.0 | 1.0 | -5745.0 | -8240.0 |
| 5.0 | 2.0 | -4237.0 | -6732.0 |
| 7.0 | 0.5 | -9602.0 | -8881.0 |
| 7.0 | 1.0 | -8899.0 | -8178.0 |
| 7.0 | 2.0 | -7391.0 | -6670.0 |

## E6. Policy sweep: thresholds tau_c and tau_I (governed agent)

| tau_conf | tau_impact | auto share | wrong-auto rate | mean J, USD/run |
|---|---|---|---|---|
| 0.6 | 1000.0 | 21.3% | 6.8% | 10208.0 |
| 0.6 | 2500.0 | 28.0% | 5.2% | 10165.0 |
| 0.6 | 5000.0 | 30.1% | 4.8% | 10150.0 |
| 0.6 | 10000.0 | 30.3% | 4.8% | 10149.0 |
| 0.7 | 1000.0 | 17.5% | 7.8% | 10219.0 |
| 0.7 | 2500.0 | 23.0% | 5.9% | 10183.0 |
| 0.7 | 5000.0 | 25.1% | 5.5% | 10169.0 |
| 0.7 | 10000.0 | 25.2% | 5.4% | 10168.0 |
| 0.8 | 1000.0 | 13.5% | 8.9% | 10118.0 |
| 0.8 | 2500.0 | 18.0% | 6.7% | 10088.0 |
| 0.8 | 5000.0 | 20.0% | 6.0% | 10075.0 |
| 0.8 | 10000.0 | 20.2% | 5.9% | 10074.0 |
| 0.9 | 1000.0 | 10.7% | 9.6% | 10059.0 |
| 0.9 | 2500.0 | 14.6% | 7.0% | 10033.0 |
| 0.9 | 5000.0 | 16.3% | 6.3% | 10023.0 |
| 0.9 | 10000.0 | 16.4% | 6.2% | 10022.0 |