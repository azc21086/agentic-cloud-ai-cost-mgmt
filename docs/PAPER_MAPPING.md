# Mapping between the paper and the code

Paper: *Agentic AI Decision Systems for Cloud Financial Governance* (second revision, Cogent Business & Management
submission 268577455). Section numbers refer to the second revision. The notes below that tell the author what "must
change" in the paper were written before the revision; they are now applied in the manuscript.

## Section 3.1 Formal specification of bounded autonomy

| Paper element | Code | Test |
|---|---|---|
| Governance object g = (e, F, I, a, c) | `gcsi.schema.GovernanceObject` | `tests/test_pipeline.py` |
| Pre-approved set A0 | `PolicyConfig.auto_actions` (no_action, recalculate_baseline, send_alert) | `tests/test_router.py` |
| Thresholds tau_I, tau_c | `PolicyConfig.tau_impact_usd` (USD per week), `tau_conf` | `tests/test_router.py` |
| Routing function rho | `gcsi.governance.router.route` | `tests/test_router.py` |
| Property (i) no material autonomy | `route`; counted in every run as `material_autonomy_violations` | random-sample test; experiment invariant |
| Property (ii) monotone escalation | `route` | random-sample test |
| Property (iii) complete trail | `GovernanceObject.decision_trail`, `AuditLog` | `test_audit_log_is_valid_jsonl` |
| Decision-economics objective | `gcsi.evaluation.runner.evaluate_run` (field `objective`), `gcsi.evaluation.economics` | `test_waste_incurred_and_effects` |

Differences between the code and the text of Section 3.1, to be reflected in the paper:

1. `AUTO` has a fourth precondition: repeated evaluations of the same evidence must agree (control iii). This only adds a
   condition to AUTO, so properties (i) and (ii) still hold.
2. The impact used for routing is `max(model-stated impact, measured impact)`. The model cannot lower the impact below the
   deviation the detector measured.
3. The confidence c is `min(adjusted model confidence, statistical confidence)` (`gcsi.governance.confidence`).
4. The objective is now evaluated with assumed values for the review cost kappa, the disruption cost and the delays, and the
   error term is the cost of wrong actions in the simulation. The paper currently states that kappa and L_error are not
   estimated; that sentence must change to "assumed, with sensitivity analysis".

## Section 4 Reasoning-layer controls

| Control | Implementation |
|---|---|
| (i) Structured output, REJECT not repair | `governance.validator.parse_json_strict` (no fence stripping, no truncation repair), `validate_record`; JSON Schema via `schema.governance_object_json_schema()` and `gcsi prompt --schema` |
| (ii) Grounding | `INPUT_REFS`; unsupported causal factors lower confidence (`PolicyConfig.unsupported_factor_penalty`); stated impact must be within a factor of the measured impact (`impact_ratio_tolerance`, rule `IMPACT_NOT_GROUNDED`); action-evidence agreement in `governance.confidence.statistical_confidence` |
| (iii) Consistency | `LLMSettings.repeats`; `agent.assess` compares action class and impact across repeats (`consistency_tolerance`); disagreement gives `INCONSISTENT_REPEATS` and routes to REVIEW |
| (iv) Bounded action space | `schema.ACTION_CATALOG`; unknown classes fail validation; `executor.py` is rule-based and reads only the routing outcome |
| (v) Logging | `governance.audit.AuditLog` (JSONL), `decision_trail` with prompt reference, policy digest and model; experiment `manifest.json` stores config digest, prompt reference, model and call counts; `llm_cache.jsonl` stores every response |

The Section 5 placeholder ("which of controls (i) to (v) the prototype implements") can now read: all five, in this package.
The first prototype implemented none of them as code.

## Section 5 Prototype implementation

| Paper statement | What the code does | Action for the paper |
|---|---|---|
| "regression and time-series models built with Pandas and Prophet" | Usage-driven regression with trend, usage and weekday terms; no Prophet | Rewrite the sentence; say why (60 usable days) |
| "point forecasts and confidence intervals" | Intervals from a robust residual scale (MAD); 80% coverage is reported in the backtest | Keep, specify the method |
| Chronological evaluation | `forecast.rolling_origin_backtest`; the first prototype used a random 80/20 split | Report WAPE against seasonal-naive and 14-day-mean baselines |
| Governance object in JSON | `schema.py`, validator, router | Table A1 gains fields `object_id`, `confidence_components`, `reason_codes`, `prompt_ref`, `policy_ref`, `model` |
| Natural-language query, visual output | `gcsi.insights`, `gcsi.ui` tab 1 | Retake Figure 4 screenshots from the new interface |
| Agentic actions are simulated | `executor.py`; the free-text "goal" planner of the first prototype is replaced by detection-driven decision records | Update the Figure 4 caption and text |

## Section 6 Evaluation

`gcsi experiment` produces `report.md` and CSV tables that map to the new evaluation tables:

| Output | Content |
|---|---|
| E1 | Detection: events detected, precision, days to alert, benign surges flagged |
| E2 | Outcomes by method: waste incurred, human load, wrong actions, wrong-auto rate, total cost J; paired differences |
| E3 | Governance layer: routing mix, schema validity, action accuracy, Brier score, repeat agreement, property (i) check, latency, tokens; injected faults by routing outcome |
| E4 | Total cost by scenario family |
| E5 | Sensitivity to human triage and review delays |
| E6 | Policy sweep over tau_c and tau_I |

The existing scenario tables (Tables 3 to 5, the 2 to 6 day agentic time to decision) remain scenario arithmetic from
`scripts/governance_simulation.py`. The experiment replaces the assumption "agentic time to decision = 2 to 6 days" with an
explicit, swept parameter (`review_days`) and measured detection delay.

## Appendices and statements

* Appendix A (Table A1): `schema.py` and `docs/governance_object.schema.json` (generate with `gcsi prompt --schema`).
* Appendix C: `scripts/governance_simulation.py` is unchanged and still reproduces Tables 3 to 5.
* Code availability: replace "available on request" with the repository URL and a Zenodo DOI for the tagged release.
* Data availability: the experiment data are generated by `gcsi.synth` and fully determined by (family, seed); no data file is needed.

## Section 6.4 of the second revision: where each table comes from

Stored run: `results/real_gpt-4o-mini/` (model gpt-4o-mini-2024-07-18, temperature 0.7, 3 repeats, no fixed seed, prompt
`decision_record_v1`, 20 simulations, 300 incidents, 900 calls). Reproduce all of it without a key:

    PYTHONPATH=src python -m gcsi.cli experiment --provider openai --model gpt-4o-mini --temperature 0.7 --repeats 3 \
        --seeds 5 --cache results/real_gpt-4o-mini/llm_cache.jsonl --max-calls 0 --out results/replay

(with `GCSI_API_KEY` set to any placeholder; `--max-calls 0` makes a live call impossible).

| Manuscript table | Source file |
|---|---|
| Table 6 injected anomaly types | `gcsi.synth` (`CAUSE_VALID_ACTIONS`), counts from `table_E1_detection.csv` and `incident_decisions.csv` |
| Table 7 detection by detector | `table_E1_detection.csv` |
| Table 8 reasoning layer and routing | `table_E3_governance.csv`, `llm_layer.csv` |
| Table 9 accuracy by incident type | `incident_decisions.csv` |
| Table 10 outcomes by method | `table_E2_outcomes.csv`, `method_results.csv` |
| Table 11 human delay sensitivity | `table_E5_delay_sweep.csv` |
| Table 12 reviewer accuracy | `table_E7_reviewer_accuracy.csv`, produced by `scripts/sensitivity_reviewer_accuracy.py` |
| Policy sweep (text) | `table_E6_policy_sweep.csv` |
| Forecast benchmark (text) | `forecast_backtest_synthetic.csv` |

Column note for E2: `Disruptive actions executed/run` counts actions that disrupt operations; `Harmful automatic actions/run`
also counts actions that explain real waste away as demand. The manuscript reports the second.
