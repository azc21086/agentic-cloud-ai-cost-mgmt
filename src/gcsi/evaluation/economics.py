"""Decision-economics simulation for one run (paper Section 3.1 objective, first terms).

For each injected waste event the method either resolves it at some time or not. Waste incurred is the injected excess
spend that occurs before resolution. Human attention, automated alerts and disruptive wrong actions carry costs.
All delays and costs are ASSUMED inputs (EconomicsConfig), not measurements. Day d covers the interval [d, d+1).
"""
from __future__ import annotations

import math

import numpy as np

from ..config import EconomicsConfig
from ..schema import ACTION_CATALOG, EXPLAINED_ACTIONS

INF = float("inf")


def action_effect(ev: dict | None, action: str) -> str:
    """Classify what executing `action` does to an incident matched to event `ev` (None means spurious)."""
    if ev is not None and ev["is_waste"]:
        valid = str(ev["valid_actions"]).split("|")
        if action in valid:
            return "fix"
        if action == "send_alert":
            return "alert"
        if action in EXPLAINED_ACTIONS:
            return "mask"
        return "misdirect"
    if action in EXPLAINED_ACTIONS:
        return "ok"
    if action == "send_alert":
        return "noise"
    return "disrupt"


HARMFUL = {"mask", "misdirect", "disrupt"}


def decision_correct(ev: dict | None, action: str) -> bool:
    e = action_effect(ev, action)
    return e in ("fix", "ok", "noise")


def executable_action(parsed) -> str | None:
    """Action an ungoverned agent would execute: any strictly parsed JSON naming a cataloged action."""
    if isinstance(parsed, dict):
        ra = parsed.get("recommended_action")
        if isinstance(ra, dict) and ra.get("class") in ACTION_CATALOG:
            return ra["class"]
    return None


def handle_incident(method: str, inc_detect_idx: int, ev: dict | None, dec, econ: EconomicsConfig, rng) -> dict:
    """Outcome of one incident under one method. `dec` is a Decision or None."""
    t0 = inc_detect_idx + 1.0  # an alert confirmed on day D can act from the start of day D+1
    out = dict(route="", touches=0, alerts=0, auto_exec=False, harmful=False, disruption=0, resolve=INF, effect="")
    waste = ev is not None and ev["is_waste"]

    def triage():
        out["touches"] += 1
        out["resolve"] = t0 + econ.human_triage_days if waste else INF

    def apply(action: str, delay: float):
        eff = action_effect(ev, action)
        out["effect"] = eff
        if eff == "fix":
            out["resolve"] = t0 + delay
        elif eff == "alert":
            out["resolve"] = t0 + econ.human_triage_days
        elif eff == "misdirect":
            out["resolve"] = t0 + delay + econ.human_triage_days
            out["disruption"] += 1
        elif eff == "disrupt":
            out["disruption"] += 1
        elif eff == "mask":
            out["resolve"] = INF
        out["harmful"] = eff in HARMFUL

    if method in ("threshold_alert", "residual_alert"):
        out["route"] = "HUMAN"
        triage()
    elif method == "agent_ungoverned":
        act = executable_action(dec.parsed)
        if act is None:
            out["route"] = "HUMAN"
            triage()
        else:
            out["route"] = "AUTO"
            out["auto_exec"] = True
            apply(act, 0.0)
    elif method == "agent_governed":
        r = dec.obj.routing
        out["route"] = r
        if r == "AUTO":
            out["auto_exec"] = True
            out["alerts"] = 1
            apply(dec.obj.action_class, 0.0)
        elif r == "REVIEW":
            out["touches"] = 1
            if rng.random() < econ.reviewer_accuracy:
                out["resolve"] = t0 + econ.review_days if waste else INF
                out["effect"] = "human_correct"
            else:
                apply(dec.obj.action_class, econ.review_days)
        else:  # REJECT
            triage()
    else:
        raise ValueError(method)
    return out


def waste_incurred(excess_by_day: np.ndarray, start_idx: int, resolve_time: float) -> float:
    """Sum of injected excess before the resolution time; day d is exposed for clip(T - d, 0, 1) of its length."""
    d = np.arange(start_idx, start_idx + len(excess_by_day), dtype=float)
    frac = np.clip(resolve_time - d, 0.0, 1.0) if math.isfinite(resolve_time) else np.ones_like(d)
    return float(np.sum(excess_by_day * frac))
