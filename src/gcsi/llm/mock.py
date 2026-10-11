"""Deterministic mock reasoning layer with optional, seeded fault injection.

The mock applies a few transparent rules to the evidence packet and emits a decision record. It exists so the whole
pipeline (validation, routing, logging, evaluation) can run and be tested with no API key. Fault injection corrupts a
share of responses in the ways real models sometimes fail, to exercise the governance layer. Results obtained with the
mock describe the pipeline under ASSUMED failure rates. They say nothing about how any real model performs.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .base import LLMResponse
from .prompts import EVIDENCE_CLOSE, EVIDENCE_OPEN

FAULTS = (
    "invalid_json",
    "missing_field",
    "unknown_action",
    "impact_distorted",
    "overconfident_misdiagnosis",
    "unsupported_factor",
)


def _extract(user: str) -> dict:
    a = user.index(EVIDENCE_OPEN) + len(EVIDENCE_OPEN)
    b = user.index(EVIDENCE_CLOSE)
    return json.loads(user[a:b])


def _clean_record(ev: dict) -> dict:
    share = ev.get("usage_explained_share")
    share = 0.0 if share is None else float(share)
    z = float(ev.get("z_score") or 0.0)
    measured = float(ev.get("impact_measured_usd_per_week") or 0.0)
    ent = ev["entity"]
    event = (
        f"{ent} spend {ev['observed_daily_spend_usd']:.0f} USD/day vs forecast {ev['expected_daily_spend_usd']:.0f} "
        f"from {ev['window']['start']} (z={z:.1f})"
    )
    if share >= 0.6:
        action, conf = "recalculate_baseline", 0.55 + 0.4 * share
        factors = [
            {"factor": "usage growth explains the spend increase", "evidence_ref": "usage_series", "share": 0.8},
            {"factor": "residual forecast error", "evidence_ref": "forecast_interval", "share": 0.2},
        ]
        why = "Usage rose in line with spend, so the deviation looks demand-driven."
    else:
        shape = ev.get("shape", "step")
        action = {"step": "stop_idle_resource", "ramp": "apply_budget_cap", "spike": "send_alert"}.get(shape, "send_alert")
        conf = 0.50 + 0.45 * float(np.clip((z - 3.0) / 6.0, 0.0, 1.0))
        factors = [
            {"factor": "spend rose without a matching rise in usage", "evidence_ref": "usage_series", "share": 0.6},
            {"factor": "spend outside the forecast interval", "evidence_ref": "forecast_interval", "share": 0.4},
        ]
        why = f"Spend rose with flat usage and a {shape} shape; treating it as possible waste."
    return {
        "event": event,
        "causal_factors": factors,
        "financial_impact": {
            "value_usd_per_week": round(measured, 2),
            "low": round(0.8 * measured, 2),
            "high": round(1.2 * measured, 2),
        },
        "recommended_action": {"class": action, "params": {"entity": ent}},
        "confidence": round(float(np.clip(conf, 0.05, 0.99)), 2),
        "rationale": why,
    }


class MockLLM:
    name = "mock-reasoner-v1"

    def __init__(self, fault_rate: float = 0.15, seed: int = 0):
        self.fault_rate = fault_rate
        self.seed = seed

    def _rng(self, ev: dict, repeat: int) -> np.random.Generator:
        h = hashlib.sha256(f"{self.seed}|{ev['incident_id']}|{repeat}".encode()).digest()
        return np.random.default_rng(int.from_bytes(h[:8], "little"))

    def complete(self, system, user, *, temperature=0.0, seed=None, repeat=0) -> LLMResponse:
        ev = _extract(user)
        rng = self._rng(ev, repeat)
        rec = _clean_record(ev)
        fault = None
        if rng.random() < self.fault_rate:
            fault = str(rng.choice(FAULTS))
        text = None
        if fault == "invalid_json":
            text = json.dumps(rec)[: int(len(json.dumps(rec)) * 0.7)]
        elif fault == "missing_field":
            rec.pop(str(rng.choice(["confidence", "recommended_action", "financial_impact"])))
        elif fault == "unknown_action":
            rec["recommended_action"] = {"class": "migrate_workloads_to_spot_fleet", "params": {}}
        elif fault == "impact_distorted":
            f = float(rng.choice([0.05, 8.0]))
            fi = rec["financial_impact"]
            rec["financial_impact"] = {k: round(v * f, 2) for k, v in fi.items()}
        elif fault == "overconfident_misdiagnosis":
            waste = rec["recommended_action"]["class"] not in ("recalculate_baseline", "no_action")
            rec["recommended_action"] = {
                "class": "recalculate_baseline" if waste else "stop_idle_resource",
                "params": {"entity": ev["entity"]},
            }
            rec["confidence"] = 0.97
            rec["rationale"] = "High confidence diagnosis."
        elif fault == "unsupported_factor":
            rec["causal_factors"] = rec["causal_factors"][:1] + [
                {"factor": "vendor price list change", "evidence_ref": "vendor_price_list", "share": 0.3}
            ]
            rec["causal_factors"][0]["share"] = 0.7
        if text is None:
            text = json.dumps(rec)
        return LLMResponse(
            text=text, model=self.name, latency_s=0.0, prompt_tokens=0, completion_tokens=0, meta={"fault": fault}
        )
