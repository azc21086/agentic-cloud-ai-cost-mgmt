"""Multi-seed experiment driver and sensitivity sweeps."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ..config import EconomicsConfig, ExperimentConfig, PolicyConfig
from ..governance import AuditLog
from ..llm import make_client, prompt_ref
from .runner import RunArtifacts, collect_run, evaluate_run


def run_experiment(cfg: ExperimentConfig, out_dir: str | Path, api_key: str | None = None, progress=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    llm = make_client(cfg.llm, api_key=api_key)
    audit = AuditLog(out / "audit.jsonl", keep_in_memory=False)
    arts: list[RunArtifacts] = []
    total = len(cfg.families) * cfg.n_seeds
    done = 0
    for fam in cfg.families:
        for i in range(cfg.n_seeds):
            seed = cfg.base_seed + i
            arts.append(collect_run(fam, seed, cfg, llm, audit))
            done += 1
            if progress and (done % 5 == 0 or done == total):
                progress(f"  collected {done}/{total} runs (live LLM calls so far: {getattr(llm, 'live_calls', 0)})")
    method_rows, inc_rows, llm_rows = [], [], []
    for a in arts:
        m, i, l = evaluate_run(a, cfg.policy, cfg.economics, audit)
        method_rows += m
        inc_rows += i
        llm_rows += l
    methods = pd.DataFrame(method_rows)
    incidents = pd.DataFrame(inc_rows)
    llm_df = pd.DataFrame(llm_rows)
    methods.to_csv(out / "method_results.csv", index=False)
    incidents.to_csv(out / "incident_decisions.csv", index=False)
    llm_df.assign(faults_by_type=llm_df["faults_by_type"].map(json.dumps)).to_csv(out / "llm_layer.csv", index=False)
    manifest = {
        "package_version": __import__("gcsi").__version__,
        "config": json.loads(json.dumps(asdict(cfg), default=str)),
        "config_digest": cfg.digest(),
        "prompt_ref": prompt_ref(),
        "llm_model": getattr(llm, "name", ""),
        "live_llm_calls": getattr(llm, "live_calls", 0),
        "cache_hits": getattr(llm, "hits", 0),
        "n_runs": len(arts),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"arts": arts, "methods": methods, "incidents": incidents, "llm": llm_df, "manifest": manifest}


def policy_sweep(arts, cfg: ExperimentConfig, tau_conf=(0.6, 0.7, 0.8, 0.9), tau_impact=(1000.0, 2500.0, 5000.0, 10000.0)):
    """Re-route stored model responses under different policies. No model calls."""
    rows = []
    for tc in tau_conf:
        for ti in tau_impact:
            pol = PolicyConfig(**{**asdict(cfg.policy), "tau_conf": tc, "tau_impact_usd": ti,
                                  "auto_actions": tuple(cfg.policy.auto_actions)})
            for a in arts:
                m, _, _ = evaluate_run(a, pol, cfg.economics)
                g = next(r for r in m if r["method"] == "agent_governed")
                rows.append({"tau_conf": tc, "tau_impact": ti, "family": a.family, "seed": a.seed, **g})
    return pd.DataFrame(rows)


def delay_sweep(arts, cfg: ExperimentConfig, triage=(1.0, 3.0, 5.0, 7.0), review=(0.5, 1.0, 2.0)):
    """Re-score under different human delays. No model calls."""
    rows = []
    for tr in triage:
        for rv in review:
            econ = EconomicsConfig(**{**asdict(cfg.economics), "human_triage_days": tr, "review_days": rv})
            for a in arts:
                m, _, _ = evaluate_run(a, cfg.policy, econ)
                for r in m:
                    rows.append({"human_triage_days": tr, "review_days": rv, **r})
    return pd.DataFrame(rows)
