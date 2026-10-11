# What changed from the first prototype (cloud_core.py, ui_gradio.py)

## Defects fixed

| First prototype | Now |
|---|---|
| `np.inf` used without importing numpy | No such code path; ratios are NaN where the denominator is zero |
| Data loading, forecasting, OpenAI client creation at import time | Import is side-effect free; everything is called explicitly |
| Model hardcoded to `gpt-4o-mini`, key typed into the UI and assigned to a module global | Provider-agnostic client; key from the environment or a per-request field; never stored |
| Random 80/20 `train_test_split` on time-ordered data (future leaks into past) | Chronological rolling-origin backtest and trailing-window fits |
| Paper says Prophet, code uses LinearRegression | Code and paper now agree (paper text to be updated) |
| Forecast = per-product regression on USERS and API_CALLS with 6-month linear extrapolation (graphs showed values far above history) | 30-day horizon, usage projected from the last 28 days, intervals shown, history before first spend dropped |
| Free-form JSON-like text split on string markers; no schema, confidence, routing or log | Strict JSON, validation, confidence, routing rule, decision trail, audit log |
| Forecast tab handlers nested in the third tab; `demo.launch()` at import | Clean layout; `launch()` is explicit |

## Numbers that change (retake Figure 4 and recheck any quoted values)

The first prototype computed "revenue-to-cost" and "cost per consumption" as means of row-level ratios, and "total spend" as
a per-row mean. Rows with tiny spend produced huge ratios (207.29 for Alpha, 189.11 for Beta) and "spend volatility" printed
`inf`. The package uses ratios of sums:

| Measure | First prototype screenshot | Now |
|---|---|---|
| Revenue-to-cost, Alpha | 207.29 | 3.33 |
| Revenue-to-cost, Beta | 189.11 | 3.49 |
| Total spend, Alpha, Beta | 0.114, 0.051 (a per-row mean) | 2,942.58 USD, 1,326.48 USD (totals) |
| Cost per consumption unit | 0.0047 (both) | 0.0560 (both) |
| Spend by region, LATAM | 1,251.30 | 1,251.30 (unchanged; half of the customers have no region on file and now show as "Unknown") |

The ranking of the two products on revenue-to-cost reverses (Beta is slightly higher on the ratio of sums). The sample data
are synthetic and tiny (4,269 USD in total over 90 days), so none of these figures is evidence about a real business. If the
paper or the response letter quotes the earlier values, remove them.
