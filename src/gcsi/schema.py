"""Governance object schema (paper Appendix A, Table A1), action catalog and incident record."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Fixed action catalog (control iv, bounded action space). The language model selects from this list.
ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "no_action": {"reversible": True, "description": "Take no action; the deviation is explained or immaterial."},
    "send_alert": {"reversible": True, "description": "Send an internal alert to the cost owner."},
    "recalculate_baseline": {"reversible": True, "description": "Re-fit the forecast baseline to the new level."},
    "stop_idle_resource": {"reversible": True, "description": "Stop or schedule down an idle or orphaned resource."},
    "rightsize_instance": {"reversible": True, "description": "Move a workload to a smaller instance class."},
    "apply_budget_cap": {"reversible": True, "description": "Apply a spend cap or quota to a runaway workload."},
    "purchase_commitment": {"reversible": False, "description": "Buy a reserved instance or savings plan."},
}

# Action classes that treat the deviation as real waste, and those that treat it as explained.
WASTE_ACTIONS = ("stop_idle_resource", "rightsize_instance", "apply_budget_cap", "purchase_commitment")
EXPLAINED_ACTIONS = ("no_action", "recalculate_baseline")

# Ground-truth cause classes used by the synthetic generator and the evaluation.
CAUSE_VALID_ACTIONS: dict[str, tuple] = {
    "idle_resource": ("stop_idle_resource", "rightsize_instance"),
    "runaway_job": ("apply_budget_cap", "stop_idle_resource"),
    "egress_spike": ("send_alert", "apply_budget_cap"),
    "benign_usage_surge": ("recalculate_baseline", "no_action"),
}
WASTE_CAUSES = ("idle_resource", "runaway_job", "egress_spike")
BENIGN_CAUSES = ("benign_usage_surge",)

# Input references the model may cite as evidence (control ii, grounding).
INPUT_REFS = ("spend_series", "usage_series", "forecast_interval", "policy")

ROUTES = ("AUTO", "REVIEW", "REJECT")

REQUIRED_FIELDS = ("event", "causal_factors", "financial_impact", "recommended_action", "confidence")


@dataclass
class Incident:
    incident_id: str
    entity: str
    start: str  # first flagged day (ISO date)
    detect: str  # day the alert was confirmed (ISO date); only data up to this day may be used
    end: str  # last flagged day in the streak (ISO date)
    detector: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GovernanceObject:
    """Machine-readable decision record g = (e, F, I, a, c) plus routing and decision trail."""

    object_id: str
    incident_id: str
    event: str
    causal_factors: list
    financial_impact: dict  # {"value_usd_per_week": x, "low": l, "high": h}
    recommended_action: dict  # {"class": str, "params": {}}
    confidence: float  # final confidence used by the router
    confidence_components: dict = field(default_factory=dict)
    routing: str = "REVIEW"
    reason_codes: list = field(default_factory=list)
    decision_trail: list = field(default_factory=list)
    model: str = ""
    prompt_ref: str = ""
    policy_ref: str = ""
    created: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def action_class(self) -> str:
        return str(self.recommended_action.get("class", ""))

    @property
    def impact_usd(self) -> float:
        return float(self.financial_impact.get("value_usd_per_week", 0.0))


def governance_object_json_schema() -> dict:
    """JSON Schema for the model-produced part of the governance object (Table A1)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "GovernanceObjectModelOutput",
        "type": "object",
        "required": list(REQUIRED_FIELDS),
        "properties": {
            "event": {"type": "string"},
            "causal_factors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["factor", "evidence_ref", "share"],
                    "properties": {
                        "factor": {"type": "string"},
                        "evidence_ref": {"type": "string", "enum": list(INPUT_REFS)},
                        "share": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "financial_impact": {
                "type": "object",
                "required": ["value_usd_per_week", "low", "high"],
                "properties": {
                    "value_usd_per_week": {"type": "number", "minimum": 0},
                    "low": {"type": "number", "minimum": 0},
                    "high": {"type": "number", "minimum": 0},
                },
            },
            "recommended_action": {
                "type": "object",
                "required": ["class"],
                "properties": {
                    "class": {"type": "string", "enum": list(ACTION_CATALOG)},
                    "params": {"type": "object"},
                },
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
    }
