"""Re-score a stored real-model run under imperfect human review (no model calls, no API key).

Usage:
  python scripts/sensitivity_reviewer_accuracy.py --cache results/real_gpt-4o-mini/llm_cache.jsonl \
      --model gpt-4o-mini --seeds 5 --repeats 3 --temperature 0.7 --out results/real_gpt-4o-mini/table_E7_reviewer_accuracy.csv

When a reviewer errs, the agent's own proposal is applied one review-delay later (so a wrong proposal does damage).
Only review of agent proposals is degraded; the human-triage baselines keep perfect triage, so this is a stress test of
the governed agent, not a symmetric comparison.
"""
import argparse
import tempfile
from dataclasses import asdict

import numpy as np
import pandas as pd
import scipy.stats as st

from gcsi.config import EconomicsConfig, ExperimentConfig, LLMSettings
from gcsi.evaluation.harness import run_experiment
from gcsi.evaluation.runner import evaluate_run


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", required=True)
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--accuracies", default="1.0,0.9,0.8,0.7,0.5")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    llm = LLMSettings(provider="openai", model=a.model, temperature=a.temperature, repeats=a.repeats, max_calls=0,
                      cache_path=a.cache)
    cfg = ExperimentConfig(n_seeds=a.seeds, llm=llm)
    with tempfile.TemporaryDirectory() as tmp:
        # max_calls=0 means any cache miss raises instead of calling a model; the key below is never used
        res = run_experiment(cfg, tmp, api_key="unused-placeholder-key-0000000000", progress=None)
    rows = []
    for acc in [float(x) for x in a.accuracies.split(",")]:
        econ = EconomicsConfig(**{**asdict(cfg.economics), "reviewer_accuracy": acc})
        allm = []
        for art in res["arts"]:
            m, _, _ = evaluate_run(art, cfg.policy, econ)
            allm += m
        d = pd.DataFrame(allm)
        j = d.groupby("method").objective.mean()
        gg = d[d.method == "agent_governed"].set_index(["family", "seed"])
        diff = gg.objective - d[d.method == "residual_alert"].set_index(["family", "seed"]).objective
        n = len(diff)
        h = st.t.ppf(0.975, n - 1) * diff.std(ddof=1) / np.sqrt(n)
        rows.append(dict(reviewer_accuracy=acc, J_governed=round(j["agent_governed"]), J_residual_alert=round(j["residual_alert"]),
                         J_ungoverned=round(j["agent_ungoverned"]), governed_minus_residual=round(diff.mean()),
                         ci_low=round(diff.mean() - h), ci_high=round(diff.mean() + h),
                         disruptive_actions_per_run=round(gg.disruptions.sum() / n, 2)))
    out = pd.DataFrame(rows)
    out.to_csv(a.out, index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
