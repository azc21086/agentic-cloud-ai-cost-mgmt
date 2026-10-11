"""Turn experiment results into Markdown tables (and CSV copies) suitable for the paper's evaluation section."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .harness import delay_sweep, policy_sweep
from .stats import fmt_ci, mean_ci, wilson

LABELS = {
    "threshold_alert": "Fixed-threshold alert (human triage)",
    "residual_alert": "Forecast-residual alert (human triage)",
    "agent_ungoverned": "Agent, ungoverned (executes every proposal)",
    "agent_governed": "Agent, governed (validation + routing rule)",
}


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def _prop(k, n, d=1):
    p, lo, hi = wilson(k, n)
    return "n/a" if np.isnan(p) else f"{100*p:.{d}f}% [{100*lo:.{d}f}, {100*hi:.{d}f}] (n={int(n)})"


def table_detection(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for meth in ("threshold_alert", "residual_alert"):
        g = m[m.method == meth]
        rows.append({
            "Detector": LABELS[meth].split(" (")[0],
            "Waste events detected": _prop(g.events_detected.sum(), g.n_waste_events.sum()),
            "Incidents on a waste event (precision)": _prop(g.incidents_on_waste.sum(), g.n_incidents.sum()),
            "Incidents per run": fmt_ci(*mean_ci(g.n_incidents), d=1),
            "Days from event start to alert": fmt_ci(*mean_ci(g.ttd_mean), d=2),
            "Benign surges flagged": _prop(g.benign_events_flagged.sum(), g.benign_events.sum()),
        })
    return pd.DataFrame(rows)


def table_outcomes(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for meth in LABELS:
        g = m[m.method == meth]
        auto, harm = g.auto_exec.sum(), g.harmful_auto.sum()
        rows.append({
            "Method": LABELS[meth],
            "Waste incurred, USD/run": fmt_ci(*mean_ci(g.waste_incurred), d=0),
            "Human reviews or triages/run": fmt_ci(*mean_ci(g.touches), d=1),
            "Disruptive actions executed/run": fmt_ci(*mean_ci(g.disruptions), d=2),
            "Harmful automatic actions/run (disruptive or masking)": fmt_ci(*mean_ci(g.harmful_auto), d=2),
            "Wrong-auto rate": _prop(harm, auto) if auto else "n/a (no autonomous action)",
            "Total cost J, USD/run": fmt_ci(*mean_ci(g.objective), d=0),
        })
    return pd.DataFrame(rows)


def _paired(m: pd.DataFrame, a: str, b: str, col: str = "objective"):
    x = m[m.method == a].set_index(["family", "seed"])[col]
    y = m[m.method == b].set_index(["family", "seed"])[col]
    return mean_ci((x - y).dropna())


def table_governance(m: pd.DataFrame, llm: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame:
    g = m[m.method == "agent_governed"]
    n = llm.decisions.sum()
    rows = [
        ("Decisions evaluated", f"{int(n)}"),
        ("Schema and business-rule valid", _prop(llm.valid.sum(), n)),
        ("Routed AUTO", _prop(g.route_auto.sum(), n)),
        ("Routed REVIEW", _prop(g.route_review.sum(), n)),
        ("Routed REJECT", _prop(g.route_reject.sum(), n)),
        ("Action matches ground truth (valid records)", _prop(llm.action_correct.sum(), llm.action_n.sum())),
        ("Brier score of final confidence (valid records)", f"{llm.brier_sum.sum() / max(llm.action_n.sum(), 1):.3f}"),
        ("Repeat-run agreement", _prop(llm.consistent.sum(), n)),
        ("Material-autonomy violations (property i; must be 0)", f"{int(g.material_autonomy_violations.sum())}"),
        ("Mean latency per decision, s", f"{llm.latency_sum.sum() / max(n, 1):.2f}"),
        ("Mean tokens per decision (in/out)", f"{llm.tokens_in.sum() / max(n, 1):.0f} / {llm.tokens_out.sum() / max(n, 1):.0f}"),
    ]
    return pd.DataFrame(rows, columns=["Measure", "Value"])


def table_faults(llm: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame | None:
    g = incidents[(incidents.method == "agent_governed") & incidents.fault.notna()]
    if g.empty:
        return None
    ct = pd.crosstab(g.fault, g.route).reindex(columns=["AUTO", "REVIEW", "REJECT"], fill_value=0)
    ct["Harmful action auto-executed"] = g[g.harmful & (g.route == "AUTO")].groupby("fault").size().reindex(ct.index, fill_value=0)
    return ct.reset_index().rename(columns={"fault": "Injected fault"})


def table_family(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fam, gf in m.groupby("family"):
        r = {"Family": fam}
        for meth in LABELS:
            r[LABELS[meth].split(" (")[0]] = fmt_ci(*mean_ci(gf[gf.method == meth].objective), d=0)
        rows.append(r)
    return pd.DataFrame(rows)


def write_report(res: dict, cfg, out_dir: str | Path, sweeps: bool = True) -> Path:
    out = Path(out_dir)
    m, llm, inc = res["methods"], res["llm"], res["incidents"]
    mock = cfg.llm.provider == "mock"
    parts = [f"# GCSI experiment report\n\nConfig digest `{res['manifest']['config_digest']}`; prompt `{res['manifest']['prompt_ref']}`; "
             f"model `{res['manifest']['llm_model']}`; runs: {len(m) // 4} ({len(cfg.families)} families x {cfg.n_seeds} seeds).\n"]
    if mock:
        parts.append("> **Mock reasoning layer.** The model here is a rule-based stand-in with deliberately injected faults "
                     f"(rate {cfg.llm.mock_fault_rate:.0%}). These results describe the pipeline under assumed failure rates and "
                     "must not be reported as the performance of any language model.\n")
    parts.append("> Delays and costs in the economics are assumptions (`EconomicsConfig`), not measurements. "
                 "Intervals are 95%: Wilson for proportions, t for means over runs.\n")
    t1, t2, t3, t5 = table_detection(m), table_outcomes(m), table_governance(m, llm, inc), table_family(m)
    parts += ["## E1. Detection\n", _md(t1), "\n## E2. Decision outcomes by method\n", _md(t2)]
    d1 = _paired(m, "agent_governed", "agent_ungoverned")
    d2 = _paired(m, "agent_governed", "residual_alert")
    d3 = _paired(m, "agent_governed", "threshold_alert")
    parts.append(
        "\nPaired difference in total cost J per run (negative favours the governed agent): "
        f"vs ungoverned {fmt_ci(*d1, d=0)}; vs residual alert {fmt_ci(*d2, d=0)}; vs threshold alert {fmt_ci(*d3, d=0)} USD.\n"
    )
    parts += ["## E3. Governance layer behaviour\n", _md(t3)]
    t4 = table_faults(llm, inc)
    if t4 is not None:
        parts += ["\nInjected faults by routing outcome (governed agent):\n", _md(t4)]
    parts += ["\n## E4. Total cost J by scenario family (USD per run)\n", _md(t5)]
    tables = {"E1_detection": t1, "E2_outcomes": t2, "E3_governance": t3, "E4_family": t5}
    if t4 is not None:
        tables["E3b_faults"] = t4
    if sweeps:
        ds = delay_sweep(res["arts"], cfg)
        pv = ds.pivot_table(index=["human_triage_days", "review_days"], columns="method", values="objective", aggfunc="mean").reset_index()
        pv["governed minus residual alert"] = (pv["agent_governed"] - pv["residual_alert"]).round(0)
        pv["governed minus ungoverned"] = (pv["agent_governed"] - pv["agent_ungoverned"]).round(0)
        pv = pv[["human_triage_days", "review_days", "governed minus residual alert", "governed minus ungoverned"]]
        parts += ["\n## E5. Sensitivity to human delays (mean difference in J, USD per run)\n", _md(pv)]
        ps = policy_sweep(res["arts"], cfg)
        g = ps.groupby(["tau_conf", "tau_impact"]).agg(
            auto=("route_auto", "sum"), review=("route_review", "sum"), reject=("route_reject", "sum"),
            harmful=("harmful_auto", "sum"), auto_exec=("auto_exec", "sum"), J=("objective", "mean"),
        ).reset_index()
        g["auto share"] = (100 * g.auto / (g.auto + g.review + g.reject)).round(1).astype(str) + "%"
        g["wrong-auto rate"] = np.where(g.auto_exec > 0, (100 * g.harmful / g.auto_exec.clip(lower=1)).round(1).astype(str) + "%", "n/a")
        g["mean J, USD/run"] = g.J.round(0)
        pt = g[["tau_conf", "tau_impact", "auto share", "wrong-auto rate", "mean J, USD/run"]]
        parts += ["\n## E6. Policy sweep: thresholds tau_c and tau_I (governed agent)\n", _md(pt)]
        tables["E5_delay_sweep"], tables["E6_policy_sweep"] = pv, pt
        ds.to_csv(out / "sweep_delays.csv", index=False)
        ps.to_csv(out / "sweep_policy.csv", index=False)
    for k, v in tables.items():
        v.to_csv(out / f"table_{k}.csv", index=False)
    (out / "report.md").write_text("\n".join(parts))
    return out / "report.md"
