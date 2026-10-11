# agentic-cloud-ai-cost-mgmt

Python package name: `gcsi-governance` (import name `gcsi`).

Reference implementation of a **bounded-autonomy decision system for cloud financial governance**. It accompanies the paper
*Agentic AI Decision Systems for Cloud Financial Governance and Optimization* (Ankit Chopra). The package turns spend
deviations into machine-checkable decision records, routes each record to automatic handling, human review or rejection with
an explicit rule, and measures the result in a controlled, labeled simulation.

Everything runs offline with a built-in mock reasoning layer. A real language model plugs in through any OpenAI-compatible
endpoint using your own key. All agentic actions are simulated: no cloud account is ever touched.

## What is in the package

| Layer (paper Section 4) | Module | What it does |
|---|---|---|
| Data acquisition | `gcsi.ingest` | Loads the prototype CSVs, a canonical panel CSV, or FinOps FOCUS 1.0 billing data into one entity panel |
| Forecasting | `gcsi.forecast` | Usage-driven regression (trend, usage, weekday terms) with chronological backtests and prediction intervals |
| Detection | `gcsi.anomaly` | Fixed-threshold alert and usage-aware forecast-residual detector; incident grouping; evidence packets |
| Reasoning | `gcsi.llm`, `gcsi.agent` | Provider-agnostic client, mock model with fault injection, prompt, replay cache, decision records |
| Governance | `gcsi.governance` | Strict validation, confidence score, routing function rho, audit log |
| Execution | `gcsi.executor` | Simulated execution gated by the routing outcome; named human approval and override |
| Evaluation | `gcsi.synth`, `gcsi.evaluation` | Labeled synthetic scenarios, four methods, economics, multi-seed runner, sweeps, report |
| Interface | `gcsi.ui` | Gradio app: Ask & Visualize, Forecast, Anomalies & Governance |

`docs/PAPER_MAPPING.md` maps every paper section, control, table and appendix to the code.

## Install

```bash
git clone https://github.com/azc21086/agentic-cloud-ai-cost-mgmt && cd agentic-cloud-ai-cost-mgmt
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"        # or: pip install -e .   for the core only (numpy, pandas, scipy, matplotlib)
pytest -q                      # 40+ tests, about 15 seconds
```

## Quick start

```bash
# 1. Detect anomalies on a dataset (sample CSVs, a panel CSV, or a FOCUS CSV)
python scripts/detect_anomalies.py --input data/sample --min-abs 0.5 --scale-floor 0.2
python scripts/detect_anomalies.py --input path/to/focus.csv --format focus

# 2. Generate labeled synthetic data (24 entities, 120 days, 9 injected events each)
python scripts/generate_synthetic_data.py --family all --n-seeds 3 --out data/synthetic

# 3. Run the controlled experiment with the mock reasoning layer (no key, about 4 minutes for 80 runs)
python scripts/run_experiment.py --seeds 20 --out results/mock

# 4. Launch the interface
python scripts/launch_ui.py            # http://127.0.0.1:7860, mock mode needs no key (set GCSI_DATA_DIR if installed non-editable)
```

## Using a real language model

The key is read from the shell environment (the package does not load `.env` files itself) and is never written to logs, caches or results.

```bash
export GCSI_API_KEY=...                       # or OPENAI_API_KEY
export GCSI_BASE_URL=https://.../v1           # optional: Azure gateway, vLLM, Ollama, OpenRouter, ...
python scripts/run_experiment.py --provider openai --seeds 5 --dry-run     # count calls first
python scripts/run_experiment.py --provider openai --model gpt-4o-mini --seeds 5 \
       --repeats 3 --temperature 0.7 --out results/real
```

Every response is cached in `results/real/llm_cache.jsonl` keyed by model, prompt, temperature, seed and repeat. Rerunning the
same command reuses the cache, so a run can be scored again, or reviewed by someone else, with no key and no new calls.
`--repeats 3` evaluates each incident three times and routes disagreeing objects to review (the consistency control).
Any other model family can be added by implementing the two-line `LLMClient` protocol in `gcsi/llm/base.py`.

## Reproducing the paper's experiment

The run reported in Section 6.4 of the paper is stored in `results/real_gpt-4o-mini/` (gpt-4o-mini-2024-07-18, temperature 0.7,
three repeats, 20 simulations, 900 model calls). To regenerate every table from the stored responses, with no key and no new
calls, see `docs/PAPER_MAPPING.md`. To repeat the run against a live model from a fresh terminal, use
`bash scripts/run_real_experiment.sh`; it asks for the key once, hidden, and never writes it to disk.
`scripts/sensitivity_reviewer_accuracy.py` repeats the reviewer-accuracy analysis (Table 12) from the stored responses.

## The method in four lines

1. A detector confirms a deviation and builds an evidence packet from data up to that day only.
2. The reasoning layer returns one JSON decision record: event, causal factors, impact in USD per week, an action chosen from a
   fixed catalog, and a confidence. Output that fails validation is **rejected, never repaired**.
3. Routing function rho: `REJECT` if invalid; `AUTO` if the action is pre-approved, the impact is at most tau_I, the confidence is
   at least tau_c and repeated evaluations agree; otherwise `REVIEW`, where nothing runs until a named human decides.
4. Every object, routing outcome, human decision and model reference is written to the decision trail and the audit log.

Final confidence is `min(model-stated confidence adjusted for unsupported factors, statistical confidence)`. Statistical
confidence comes from the measured evidence and from whether the chosen action agrees with the data (for example, calling a
deviation demand-driven is only supported to the extent that usage explains it). The model cannot reach AUTO on its own say-so.

## The experiment

Four independent scenario families (`steady`, `volatile`, `growth`, `lumpy`) each generate 24 entities over 120 days with six
injected waste events (idle resource, runaway job, egress spike) and three benign usage surges. Ground truth is returned with
the data. Four methods are scored on identical data:

| Method | Detection | Handling |
|---|---|---|
| Fixed-threshold alert | spend above trailing mean by 30% | human triage of every alert |
| Forecast-residual alert | usage-aware residual, persistence rule | human triage of every alert |
| Agent, ungoverned | same detector | executes whatever the model proposes |
| Agent, governed | same detector | validation, confidence, routing rule |

Reported measures: waste events detected, precision, days to alert, human reviews, wrong actions executed, wrong-auto rate,
total cost J (waste incurred plus review, alert and disruption costs), schema validity, action accuracy, Brier score of the
confidence, repeat-run agreement, latency, tokens, and a count of property (i) violations (must be zero). Sweeps cover human
delays and the thresholds tau_c and tau_I and need no further model calls.

## Read this before quoting results

* **The mock model is not a language model.** It applies transparent rules and corrupts a configurable share of its answers
  (default 15%) in six ways. Mock results show the pipeline and the governance layer under *assumed* failure rates. Do not
  report them as the performance of any model. Real-model results come from `--provider openai`.
* **Delays and costs are assumptions.** Human triage time, review time, review cost and disruption cost are inputs
  (`EconomicsConfig`), not measurements. Report the sweeps, not just the base case: the sign of the saving depends on them.
* **The data are synthetic.** The generator builds in a usage-to-spend relationship that the usage-aware detector can exploit.
  The `lumpy` family is the stress case (workload onboarding looks like a deviation) and the `volatile` family has high noise.
  Evidence on real billing data is a separate step (see `gcsi detect --format focus`).
* The thresholds (tau_I = 5,000 USD per week, tau_c = 0.80), the confidence function and the impact-grounding tolerance are
  illustrative policy choices, not calibrated values.
* Proportions use Wilson intervals and means use t intervals over runs. Incidents within a run are not independent, so
  intervals on pooled incident counts are somewhat optimistic.

## Layout

```
src/gcsi/        package (see table above)
scripts/         thin wrappers: detect_anomalies, generate_synthetic_data, run_experiment, launch_ui,
                 sensitivity_reviewer_accuracy, run_real_experiment.sh, set_github_account.sh,
                 governance_simulation.py (the paper's Appendix C scenario script, stdlib only)
tests/           pytest suite (router properties, validation, no-lookahead, adapters, experiment, UI)
data/sample/     the prototype's synthetic CSVs
docs/            paper mapping, migration notes from the first prototype
results/         example mock run (mock_example/) and the stored run behind Section 6.4 (real_gpt-4o-mini/)
```

## License and attribution

MIT. The FOCUS loader targets the FinOps Foundation FOCUS 1.0 specification; the public FOCUS sample data are CC BY 4.0 and are
not redistributed here. Cite via `CITATION.cff`.
