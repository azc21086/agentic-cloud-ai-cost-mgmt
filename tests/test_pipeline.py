import json

import pytest

from gcsi import synth
from gcsi.agent import assess, decide
from gcsi.anomaly import attach_evidence, build_incidents, residual_detector
from gcsi.config import LLMSettings, PolicyConfig
from gcsi.executor import execute, human_decision
from gcsi.governance import AuditLog
from gcsi.llm import CachedLLM, LLMResponse, MockLLM, make_client

POL = PolicyConfig()


@pytest.fixture(scope="module")
def incidents():
    ds = synth.generate("steady", 1)
    d = residual_detector(ds.panel)
    return attach_evidence(build_incidents(d, "residual", tag="t"), d, POL)


class Fixed:
    name = "fixed"

    def __init__(self, text):
        self.text = text

    def complete(self, system, user, **kw):
        return LLMResponse(text=self.text, model="fixed")


def test_clean_mock_gives_valid_objects_with_trail(incidents):
    llm = MockLLM(fault_rate=0.0)
    audit = AuditLog()
    for inc in incidents:
        d = decide(inc, llm, POL, LLMSettings(), audit)
        assert d.valid and d.obj.routing in ("AUTO", "REVIEW")
        assert d.obj.decision_trail and d.obj.decision_trail[0]["actor"] == "system"
        assert d.obj.prompt_ref.startswith("decision_record_v1") and d.obj.policy_ref
    assert len(audit.events) == len(incidents)


def test_invalid_output_is_rejected_not_repaired(incidents):
    inc = incidents[0]
    for text in ["", "not json", "```json\n{}\n```", json.dumps({"event": "x"})]:
        d = assess(inc, [LLMResponse(text=text, model="m")], POL)
        assert d.obj.routing == "REJECT" and not d.valid


def test_overconfident_wrong_answer_never_reaches_auto(incidents):
    """Mock fault 'overconfident_misdiagnosis' states confidence 0.97 with the opposite diagnosis."""
    seen = 0
    for s in range(40):
        llm = MockLLM(fault_rate=1.0, seed=s)
        for inc in incidents:
            d = decide(inc, llm, POL, LLMSettings())
            if d.llm_meta["fault"] == "overconfident_misdiagnosis":
                seen += 1
                assert d.valid and d.obj.routing == "REVIEW", (d.obj.routing, d.obj.reason_codes)
                assert d.obj.confidence_components["model_stated"] == 0.97
                assert d.obj.confidence < POL.tau_conf
    assert seen >= 10


def test_every_injected_fault_type_is_contained(incidents):
    """No injected fault may produce an AUTO decision whose action is harmful."""
    escaped = 0
    for s in range(20):
        llm = MockLLM(fault_rate=1.0, seed=s)
        for inc in incidents:
            d = decide(inc, llm, POL, LLMSettings())
            if d.obj.routing == "AUTO" and d.llm_meta["fault"] in ("overconfident_misdiagnosis", "unknown_action", "invalid_json", "missing_field", "impact_distorted"):
                escaped += 1
    assert escaped == 0


def test_confidence_cannot_be_raised_by_the_model(incidents):
    """A waste action on an incident that usage explains stays out of AUTO even at stated confidence 1.0."""
    inc = incidents[0]
    ev = dict(inc.evidence, usage_explained_share=0.95)
    inc2 = type(inc)(**{**inc.to_dict(), "evidence": ev})
    rec = {
        "event": "x", "causal_factors": [{"factor": "f", "evidence_ref": "usage_series", "share": 1.0}],
        "financial_impact": {"value_usd_per_week": ev["impact_measured_usd_per_week"], "low": 0, "high": 1e9},
        "recommended_action": {"class": "stop_idle_resource", "params": {}}, "confidence": 1.0,
    }
    d = assess(inc2, [LLMResponse(text=json.dumps(rec), model="m")], POL)
    assert d.obj.routing == "REVIEW" and d.obj.confidence < POL.tau_conf


def test_inconsistent_repeats_force_review(incidents):
    inc = incidents[0]
    ev = inc.evidence
    base = {
        "event": "x", "causal_factors": [{"factor": "f", "evidence_ref": "usage_series", "share": 1.0}],
        "financial_impact": {"value_usd_per_week": ev["impact_measured_usd_per_week"], "low": 0, "high": 1e9},
        "recommended_action": {"class": "send_alert", "params": {}}, "confidence": 0.99,
    }
    other = dict(base, recommended_action={"class": "apply_budget_cap", "params": {}})
    ev2 = dict(ev, z_score=12.0, persistence_days=3, usage_explained_share=0.0, impact_measured_usd_per_week=100.0)
    inc2 = type(inc)(**{**inc.to_dict(), "evidence": ev2})
    base["financial_impact"]["value_usd_per_week"] = 100.0
    other["financial_impact"] = dict(base["financial_impact"])
    same = assess(inc2, [LLMResponse(text=json.dumps(base), model="m")] * 2, POL)
    diff = assess(inc2, [LLMResponse(text=json.dumps(base), model="m"), LLMResponse(text=json.dumps(other), model="m")], POL)
    assert same.obj.routing == "AUTO" and same.consistent
    assert diff.obj.routing == "REVIEW" and "INCONSISTENT_REPEATS" in diff.obj.reason_codes


def test_executor_respects_routing_and_requires_named_approver(incidents):
    llm = MockLLM(fault_rate=0.0)
    objs = [decide(i, llm, POL).obj for i in incidents]
    review = next(o for o in objs if o.routing == "REVIEW")
    assert execute(review).status == "PENDING_APPROVAL"
    with pytest.raises(ValueError):
        human_decision(review, "  ", True)
    with pytest.raises(ValueError):
        human_decision(review, "x", True, override_action="not_in_catalog")
    res = human_decision(review, "Ankit", True, "ok")
    assert res.status == "SIMULATED_EXECUTED" and review.decision_trail[-2]["actor"] == "Ankit"
    auto = [o for o in objs if o.routing == "AUTO"]
    if auto:
        assert execute(auto[0]).status == "SIMULATED_EXECUTED"
        with pytest.raises(ValueError):
            human_decision(auto[0], "x", True)


def test_cache_replays_and_caps_live_calls(tmp_path):
    inner = MockLLM(fault_rate=0.0)
    path = tmp_path / "c.jsonl"
    c = CachedLLM(inner, path=str(path), max_calls=1)
    u = "<<<EVIDENCE\n" + json.dumps({"incident_id": "a", "entity": "e", "observed_daily_spend_usd": 1, "expected_daily_spend_usd": 1, "window": {"start": "x"}, "impact_measured_usd_per_week": 1}) + "\nEVIDENCE>>>"
    r1 = c.complete("s", u)
    r2 = c.complete("s", u)
    assert r2.cached and r1.text == r2.text and c.live_calls == 1
    with pytest.raises(RuntimeError):
        c.complete("s", u + " ")
    c2 = CachedLLM(inner, path=str(path))
    assert c2.complete("s", u).cached


def test_make_client_mock_needs_no_key():
    assert make_client(LLMSettings(provider="mock")).name.startswith("mock")
