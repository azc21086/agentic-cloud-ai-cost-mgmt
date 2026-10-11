"""Command line interface: gcsi {synth, detect, forecast, experiment, prompt, ui}."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd


def _cmd_synth(a):
    from . import synth

    fams = list(synth.FAMILIES) if a.family == "all" else [a.family]
    for fam in fams:
        for i in range(a.n_seeds):
            ds = synth.generate(fam, a.seed + i, n_days=a.days)
            p = synth.save(ds, Path(a.out) / f"{fam}_{a.seed + i}")
            print(f"wrote {p}  ({len(ds.panel)} rows, {len(ds.events)} injected events)")


def _cmd_detect(a):
    from . import ingest
    from .anomaly import attach_evidence, build_incidents, residual_detector, threshold_detector
    from .config import PolicyConfig, ResidualConfig, ThresholdConfig

    panel = ingest.load_any(a.input, a.format)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pol = PolicyConfig()
    res = ResidualConfig(
        z_thresh=a.z, persistence=a.persistence, min_abs_excess_usd=a.min_abs, scale_floor_abs=a.scale_floor
    )
    thr = ThresholdConfig(pct=a.pct, min_abs_excess_usd=a.min_abs)
    for name in ("residual", "threshold") if a.detector == "both" else (a.detector,):
        daily = residual_detector(panel, res) if name == "residual" else threshold_detector(panel, thr)
        incs = build_incidents(daily, name)
        if name == "residual":
            attach_evidence(incs, daily, pol)
        daily.to_csv(out / f"daily_{name}.csv", index=False)
        pd.DataFrame([i.to_dict() | {"evidence": json.dumps(i.evidence)} for i in incs]).to_csv(out / f"incidents_{name}.csv", index=False)
        print(f"{name}: {len(incs)} incident(s) on {panel['entity'].nunique()} entities -> {out}")
        for i in incs[:10]:
            print(f"  {i.entity}  start {i.start}  alert {i.detect}  end {i.end}")


def _cmd_forecast(a):
    from . import forecast as fc
    from . import ingest

    panel = ingest.load_any(a.input, a.format)
    print(fc.backtest_table(panel).round(3).to_string(index=False))
    for prod in sorted(panel["product"].unique()):
        s = fc.trim_leading_zeros(fc.product_series(panel, prod))
        if len(s) >= 21:
            f = fc.forecast_future(s, a.horizon)
            Path(a.out).mkdir(parents=True, exist_ok=True)
            f.to_csv(Path(a.out) / f"forecast_{prod}.csv", index=False)
            print(f"{prod}: forecast written ({a.horizon} days)")


def _cmd_experiment(a):
    from .config import EconomicsConfig, ExperimentConfig, LLMSettings, PolicyConfig
    from .evaluation import count_llm_calls, run_experiment, write_report

    llm = LLMSettings(
        provider=a.provider, model=a.model, base_url=a.base_url, temperature=a.temperature, seed=a.llm_seed,
        repeats=a.repeats, max_calls=a.max_calls, cache_path=a.cache or (str(Path(a.out) / "llm_cache.jsonl") if a.provider != "mock" else None),
        mock_fault_rate=a.fault_rate,
    )
    cfg = ExperimentConfig(
        families=tuple(a.families.split(",")), n_seeds=a.seeds, base_seed=a.base_seed, n_days=a.days,
        policy=PolicyConfig(tau_impact_usd=a.tau_impact, tau_conf=a.tau_conf),
        economics=EconomicsConfig(human_triage_days=a.triage_days, review_days=a.review_days,
                                  kappa_review_usd=a.kappa, disruption_cost_usd=a.disruption_cost),
        llm=llm,
    )
    if a.dry_run:
        c = count_llm_calls(cfg)
        print(json.dumps(c, indent=2))
        print("Each call sends one evidence packet (about 700 tokens) and returns about 250 tokens.")
        return
    key = os.environ.get("GCSI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if a.provider == "openai" and not key:
        sys.exit("set GCSI_API_KEY (or OPENAI_API_KEY) in the environment; the key is never written to disk")
    res = run_experiment(cfg, a.out, api_key=key)
    p = write_report(res, cfg, a.out, sweeps=not a.no_sweeps)
    print(f"report: {p}")


def _cmd_prompt(a):
    from .llm import SYSTEM_PROMPT, build_user_prompt, prompt_ref
    from .schema import governance_object_json_schema

    print(f"# {prompt_ref()}\n\n## System prompt\n{SYSTEM_PROMPT}\n\n## Example user prompt\n")
    print(build_user_prompt({"incident_id": "example", "entity": "Alpha|AWS|compute", "...": "evidence fields"}))
    if a.schema:
        print("\n## JSON Schema of the model output\n" + json.dumps(governance_object_json_schema(), indent=2))


def _cmd_ui(a):
    from .ui import launch

    launch(server_name=a.host, server_port=a.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gcsi", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth", help="generate labeled synthetic datasets")
    s.add_argument("--family", default="all", help="steady|volatile|growth|lumpy|all")
    s.add_argument("--seed", type=int, default=1000)
    s.add_argument("--n-seeds", type=int, default=1)
    s.add_argument("--days", type=int, default=120)
    s.add_argument("--out", default="data/synthetic")
    s.set_defaults(fn=_cmd_synth)

    d = sub.add_parser("detect", help="run anomaly detectors on a dataset")
    d.add_argument("--input", required=True, help="sample directory, panel CSV, or FOCUS CSV")
    d.add_argument("--format", default="auto", choices=["auto", "sample", "panel", "focus"])
    d.add_argument("--detector", default="both", choices=["residual", "threshold", "both"])
    d.add_argument("--z", type=float, default=3.5, help="residual z threshold")
    d.add_argument("--persistence", type=int, default=2, help="consecutive flagged days to confirm")
    d.add_argument("--pct", type=float, default=0.30, help="threshold detector: increase over trailing mean")
    d.add_argument("--min-abs", type=float, default=25.0, help="minimum excess in USD per day to flag")
    d.add_argument("--scale-floor", type=float, default=10.0, help="minimum residual scale in USD")
    d.add_argument("--out", default="results/detect")
    d.set_defaults(fn=_cmd_detect)

    f = sub.add_parser("forecast", help="backtest and forecast")
    f.add_argument("--input", required=True)
    f.add_argument("--format", default="auto", choices=["auto", "sample", "panel", "focus"])
    f.add_argument("--horizon", type=int, default=30)
    f.add_argument("--out", default="results/forecast")
    f.set_defaults(fn=_cmd_forecast)

    e = sub.add_parser("experiment", help="multi-seed controlled experiment with report")
    e.add_argument("--provider", default="mock", choices=["mock", "openai"], help="openai = any OpenAI-compatible endpoint")
    e.add_argument("--model", default=os.environ.get("GCSI_MODEL", "gpt-4o-mini"))
    e.add_argument("--base-url", default=os.environ.get("GCSI_BASE_URL"))
    e.add_argument("--temperature", type=float, default=0.0)
    e.add_argument("--llm-seed", type=int, default=None)
    e.add_argument("--repeats", type=int, default=1, help="evaluations per incident (consistency control)")
    e.add_argument("--max-calls", type=int, default=None, help="stop before exceeding this many live model calls")
    e.add_argument("--cache", default=None, help="JSONL cache of model responses (enables replay without a key)")
    e.add_argument("--fault-rate", type=float, default=0.15, help="mock only")
    e.add_argument("--families", default="steady,volatile,growth,lumpy")
    e.add_argument("--seeds", type=int, default=20)
    e.add_argument("--base-seed", type=int, default=1000)
    e.add_argument("--days", type=int, default=120)
    e.add_argument("--tau-impact", type=float, default=5000.0)
    e.add_argument("--tau-conf", type=float, default=0.80)
    e.add_argument("--triage-days", type=float, default=3.0)
    e.add_argument("--review-days", type=float, default=1.0)
    e.add_argument("--kappa", type=float, default=50.0)
    e.add_argument("--disruption-cost", type=float, default=2000.0)
    e.add_argument("--no-sweeps", action="store_true")
    e.add_argument("--dry-run", action="store_true", help="count the model calls a run would need, then exit")
    e.add_argument("--out", default="results/experiment")
    e.set_defaults(fn=_cmd_experiment)

    p = sub.add_parser("prompt", help="print the system prompt and output schema")
    p.add_argument("--schema", action="store_true")
    p.set_defaults(fn=_cmd_prompt)

    u = sub.add_parser("ui", help="launch the web interface")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=7860)
    u.set_defaults(fn=_cmd_ui)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
