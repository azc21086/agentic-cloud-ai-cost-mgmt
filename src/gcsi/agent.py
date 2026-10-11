"""Reasoning layer plus governance: evidence packet -> model -> validation -> confidence -> routing -> decision record."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import LLMSettings, PolicyConfig
from .governance import AuditLog, combine, parse_json_strict, route, trail_entry, validate_record
from .governance.audit import now_iso
from .llm import SYSTEM_PROMPT, build_user_prompt, prompt_ref
from .schema import GovernanceObject, Incident


@dataclass
class Decision:
    incident_id: str
    obj: GovernanceObject
    raw_text: str
    parsed: dict | None  # strictly parsed model output (may be invalid against the schema)
    valid: bool
    errors: list = field(default_factory=list)
    consistent: bool = True
    llm_meta: dict = field(default_factory=dict)


def _agree(a: dict, b: dict, tol: float) -> bool:
    if a["recommended_action"]["class"] != b["recommended_action"]["class"]:
        return False
    x, y = a["financial_impact"]["value_usd_per_week"], b["financial_impact"]["value_usd_per_week"]
    return abs(x - y) <= tol * max(x, y, 1.0)


def query_model(incident: Incident, llm, settings: LLMSettings = LLMSettings()) -> list:
    """Call the reasoning layer `settings.repeats` times on the same evidence packet."""
    user = build_user_prompt(incident.evidence)
    return [
        llm.complete(SYSTEM_PROMPT, user, temperature=settings.temperature, seed=settings.seed, repeat=r)
        for r in range(max(1, settings.repeats))
    ]


def assess(
    incident: Incident,
    responses: list,
    policy: PolicyConfig,
    audit: AuditLog | None = None,
    run_id: str = "",
) -> Decision:
    """Validate, score and route stored model responses. Pure function of (responses, policy): no model calls."""
    ev = incident.evidence
    first = responses[0]
    parsed = parse_json_strict(first.text)
    v = validate_record(parsed, ev, policy)

    consistent = True
    if len(responses) > 1:
        others = [validate_record(parse_json_strict(r.text), ev, policy) for r in responses[1:]]
        consistent = v.ok and all(o.ok and _agree(v.record, o.record, policy.consistency_tolerance) for o in others)

    measured = float(ev.get("impact_measured_usd_per_week") or 0.0)
    if v.ok:
        rec = v.record
        action = rec["recommended_action"]["class"]
        comps = combine(rec["confidence"], v.n_unsupported, action, ev, policy)
        impact = max(rec["financial_impact"]["value_usd_per_week"], measured)  # never route on less than measured
        result = route(True, action, impact, comps["final"], policy, consistent)
        obj = GovernanceObject(
            object_id=f"g:{incident.incident_id}",
            incident_id=incident.incident_id,
            event=rec["event"],
            causal_factors=rec["causal_factors"],
            financial_impact={**rec["financial_impact"], "routing_value_usd_per_week": round(impact, 2)},
            recommended_action=rec["recommended_action"],
            confidence=comps["final"],
            confidence_components=comps,
        )
    else:
        result = route(False, "", 0.0, 0.0, policy)
        obj = GovernanceObject(
            object_id=f"g:{incident.incident_id}",
            incident_id=incident.incident_id,
            event=f"deviation on {incident.entity} from {incident.start}",
            causal_factors=[],
            financial_impact={"value_usd_per_week": measured, "low": measured, "high": measured},
            recommended_action={"class": "send_alert", "params": {"entity": incident.entity}},
            confidence=0.0,
            confidence_components={},
        )
    obj.routing = result.outcome
    obj.reason_codes = list(result.reason_codes) + ([] if v.ok else list(v.errors))
    obj.model = first.model
    obj.prompt_ref = prompt_ref()
    obj.policy_ref = policy.digest()
    obj.created = now_iso()
    obj.decision_trail.append(trail_entry("system", f"ROUTED_{result.outcome}", ";".join(obj.reason_codes)))
    meta = {
        "latency_s": first.latency_s,
        "prompt_tokens": first.prompt_tokens,
        "completion_tokens": first.completion_tokens,
        "cached": first.cached,
        "fault": (first.meta or {}).get("fault"),
        "error": first.error,
    }
    d = Decision(incident.incident_id, obj, first.text, parsed, v.ok, list(v.errors), consistent, meta)
    if audit:
        audit.write(
            "decision",
            {"run_id": run_id, "incident_id": incident.incident_id, "routing": obj.routing,
             "reason_codes": obj.reason_codes, "action": obj.action_class, "impact_usd": obj.impact_usd,
             "confidence": obj.confidence, "consistent": consistent, "model": obj.model,
             "prompt_ref": obj.prompt_ref, "policy_ref": obj.policy_ref, "llm": meta},
        )
    return d


def decide(
    incident: Incident,
    llm,
    policy: PolicyConfig,
    settings: LLMSettings = LLMSettings(),
    audit: AuditLog | None = None,
    run_id: str = "",
) -> Decision:
    return assess(incident, query_model(incident, llm, settings), policy, audit, run_id)
