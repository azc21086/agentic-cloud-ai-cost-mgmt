"""Run one scenario: generate data, detect, query the reasoning layer (once), then score every method.

`collect_run` is the only step that calls the model. `evaluate_run` is a pure function of the stored responses, the policy
and the economics parameters, so threshold sweeps and sensitivity analyses cost no further model calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import synth
from ..agent import Decision, assess, query_model
from ..anomaly import attach_evidence, build_incidents, residual_detector, threshold_detector
from ..config import EconomicsConfig, ExperimentConfig, PolicyConfig
from ..governance import AuditLog
from ..schema import Incident
from .economics import decision_correct, handle_incident, waste_incurred

METHODS = ("threshold_alert", "residual_alert", "agent_ungoverned", "agent_governed")


@dataclass
class RunArtifacts:
    family: str
    seed: int
    ds: synth.SynthDataset
    inc_thr: list
    inc_res: list
    responses: dict = field(default_factory=dict)  # incident_id -> list[LLMResponse]


def _idx(ds: synth.SynthDataset, day: str) -> int:
    return int((pd.Timestamp(day) - ds.panel["date"].min()).days)


def match_incidents(ds: synth.SynthDataset, incidents: list[Incident], grace: int = 3) -> dict:
    """Map incident_id -> event row (dict) or None. An incident matches an event on the same entity if its window
    overlaps the event window extended by one day before and `grace` days after."""
    by_ent: dict[str, list] = {}
    for r in ds.events.to_dict("records"):
        by_ent.setdefault(r["entity"], []).append(r)
    out = {}
    for inc in incidents:
        hit = None
        for ev in by_ent.get(inc.entity, []):
            if _idx(ds, inc.start) <= ev["end_idx"] + grace and _idx(ds, inc.end) >= ev["start_idx"] - 1:
                hit = ev
                break
        out[inc.incident_id] = hit
    return out


def collect_run(family: str, seed: int, cfg: ExperimentConfig, llm, audit: AuditLog | None = None) -> RunArtifacts:
    ds = synth.generate(family, seed, n_days=cfg.n_days, n_waste=cfg.n_waste_events, n_benign=cfg.n_benign_events)
    tag = f"{family}{seed}"
    det_t = threshold_detector(ds.panel, cfg.threshold)
    det_r = residual_detector(ds.panel, cfg.residual)
    inc_t = build_incidents(det_t, "threshold", tag=tag)
    inc_r = attach_evidence(build_incidents(det_r, "residual", tag=tag), det_r, cfg.policy)
    art = RunArtifacts(family, seed, ds, inc_t, inc_r)
    for inc in inc_r:
        art.responses[inc.incident_id] = query_model(inc, llm, cfg.llm)
    if audit:
        audit.write("run_collected", {"family": family, "seed": seed, "n_incidents_residual": len(inc_r),
                                      "n_incidents_threshold": len(inc_t)})
    return art


def count_llm_calls(cfg: ExperimentConfig) -> dict:
    """Detect incidents for every scenario without calling the model, to size a real-LLM run."""
    n_inc = 0
    per_family = {}
    for fam in cfg.families:
        k = 0
        for i in range(cfg.n_seeds):
            ds = synth.generate(fam, cfg.base_seed + i, n_days=cfg.n_days, n_waste=cfg.n_waste_events,
                                n_benign=cfg.n_benign_events)
            d = residual_detector(ds.panel, cfg.residual)
            k += len(build_incidents(d, "residual"))
        per_family[fam] = k
        n_inc += k
    return {"incidents": n_inc, "calls": n_inc * max(1, cfg.llm.repeats), "per_family": per_family}


def _event_excess(ds: synth.SynthDataset, ev: dict) -> np.ndarray:
    ex = ds.excess[ds.excess["entity"] == ev["entity"]].sort_values("date")
    arr = np.zeros(ev["duration_days"])
    for d, v in zip(ex["date"], ex["excess"]):
        k = _idx(ds, d) - ev["start_idx"]
        if 0 <= k < len(arr):
            arr[k] = v
    return arr


def evaluate_run(
    art: RunArtifacts, policy: PolicyConfig, econ: EconomicsConfig, audit: AuditLog | None = None
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (method rows, incident rows, llm-layer row list) for one run."""
    ds = art.ds
    run_id = f"{art.family}:{art.seed}"
    events = ds.events.to_dict("records")
    waste_events = [e for e in events if e["is_waste"]]
    benign_events = [e for e in events if not e["is_waste"]]
    rng = np.random.default_rng([art.seed, 7, len(art.family)])

    dec: dict[str, Decision] = {
        inc.incident_id: assess(inc, art.responses[inc.incident_id], policy, audit, run_id) for inc in art.inc_res
    }
    m_thr = match_incidents(ds, art.inc_thr)
    m_res = match_incidents(ds, art.inc_res)

    method_rows, inc_rows = [], []
    total_waste = float(sum(e["total_excess_usd"] for e in waste_events))
    ex_prof = {e["event_id"]: _event_excess(ds, e) for e in waste_events}

    for method in METHODS:
        incs = art.inc_thr if method == "threshold_alert" else art.inc_res
        match = m_thr if method == "threshold_alert" else m_res
        touches = alerts = auto_exec = harmful = disruptions = 0
        route_counts = {"AUTO": 0, "REVIEW": 0, "REJECT": 0, "HUMAN": 0}
        resolve_by_event: dict[str, float] = {}
        first_detect: dict[str, int] = {}
        matched_waste = 0
        for inc in incs:
            ev = match[inc.incident_id]
            d_idx = _idx(ds, inc.detect)
            out = handle_incident(method, d_idx, ev, dec.get(inc.incident_id), econ, rng)
            touches += out["touches"]
            alerts += out["alerts"]
            auto_exec += int(out["auto_exec"])
            harmful += int(out["auto_exec"] and out["harmful"])
            disruptions += out["disruption"]
            route_counts[out["route"]] += 1
            if ev is not None and ev["is_waste"]:
                matched_waste += 1
                k = ev["event_id"]
                resolve_by_event[k] = min(resolve_by_event.get(k, math.inf), out["resolve"])
                first_detect[k] = min(first_detect.get(k, 10**9), d_idx)
            if method in ("agent_governed", "agent_ungoverned"):
                dd = dec[inc.incident_id]
                inc_rows.append(
                    dict(run=run_id, method=method, incident_id=inc.incident_id, entity=inc.entity, start=inc.start,
                         detect=inc.detect, event_kind=None if ev is None else ev["kind"], route=out["route"],
                         action=dd.obj.action_class, valid=dd.valid, confidence=dd.obj.confidence,
                         impact_usd=dd.obj.financial_impact.get("routing_value_usd_per_week"),
                         effect=out["effect"], harmful=out["harmful"], fault=dd.llm_meta.get("fault"),
                         reasons="|".join(dd.obj.reason_codes))
                )
        incurred = 0.0
        for e in waste_events:
            T = resolve_by_event.get(e["event_id"], math.inf)
            incurred += waste_incurred(ex_prof[e["event_id"]], e["start_idx"], T)
        n_inc = len(incs)
        detected = [e for e in waste_events if e["event_id"] in first_detect]
        ttd = [max(0, first_detect[e["event_id"]] - e["start_idx"]) for e in detected]
        matched_ids = {match[i.incident_id]["event_id"] for i in incs if match[i.incident_id] is not None}
        benign_hit = sum(1 for e in benign_events if e["event_id"] in matched_ids)
        cost_review = econ.kappa_review_usd * touches
        cost_alert = econ.kappa_alert_usd * alerts
        cost_disr = econ.disruption_cost_usd * disruptions
        row = dict(
            family=art.family, seed=art.seed, method=method,
            n_incidents=n_inc, n_waste_events=len(waste_events), events_detected=len(detected),
            incidents_on_waste=matched_waste, benign_events=len(benign_events), benign_events_flagged=benign_hit,
            ttd_mean=float(np.mean(ttd)) if ttd else float("nan"),
            touches=touches, auto_exec=auto_exec, harmful_auto=harmful, disruptions=disruptions,
            route_auto=route_counts["AUTO"], route_review=route_counts["REVIEW"], route_reject=route_counts["REJECT"],
            waste_total=total_waste, waste_incurred=incurred, saving_usd=total_waste - incurred,
            cost_review=cost_review, cost_alert=cost_alert, cost_disruption=cost_disr,
            objective=incurred + cost_review + cost_alert + cost_disr,
        )
        if method == "agent_governed":
            row["material_autonomy_violations"] = sum(
                1 for d in dec.values() if d.obj.routing == "AUTO" and d.obj.financial_impact.get("routing_value_usd_per_week", 0) > policy.tau_impact_usd
            )
        method_rows.append(row)

    # ---- reasoning-layer statistics (same decisions feed both agent methods)
    n = len(dec)
    valid = sum(1 for d in dec.values() if d.valid)
    cons = [d.consistent for d in dec.values()]
    briers, acc_ok, acc_n = [], 0, 0
    fault_rows: dict = {}
    lat, tok_in, tok_out = [], [], []
    for inc in art.inc_res:
        d = dec[inc.incident_id]
        ev = m_res[inc.incident_id]
        if d.valid:
            ok = decision_correct(ev, d.obj.action_class)
            briers.append((d.obj.confidence - float(ok)) ** 2)
            acc_ok += int(ok)
            acc_n += 1
        f = d.llm_meta.get("fault")
        if f:
            fault_rows.setdefault(f, {"AUTO": 0, "REVIEW": 0, "REJECT": 0})[d.obj.routing] += 1
        lat.append(d.llm_meta.get("latency_s") or 0.0)
        tok_in.append(d.llm_meta.get("prompt_tokens") or 0)
        tok_out.append(d.llm_meta.get("completion_tokens") or 0)
    llm_row = dict(
        family=art.family, seed=art.seed, decisions=n, valid=valid, consistent=int(sum(cons)),
        action_correct=acc_ok, action_n=acc_n, brier_sum=float(np.sum(briers)) if briers else 0.0,
        faults=sum(sum(v.values()) for v in fault_rows.values()), faults_by_type=fault_rows,
        latency_sum=float(np.sum(lat)), tokens_in=int(np.sum(tok_in)), tokens_out=int(np.sum(tok_out)),
    )
    return method_rows, inc_rows, [llm_row]
