import numpy as np

from gcsi.config import PolicyConfig
from gcsi.governance import route

POL = PolicyConfig(tau_impact_usd=5000.0, tau_conf=0.8)
A0 = list(POL.auto_actions)
OTHER = ["stop_idle_resource", "rightsize_instance", "apply_budget_cap", "purchase_commitment"]


def test_basic_outcomes():
    assert route(False, "send_alert", 10, 0.99, POL).outcome == "REJECT"
    assert route(True, "send_alert", 100, 0.9, POL).outcome == "AUTO"
    assert route(True, "stop_idle_resource", 100, 0.99, POL).outcome == "REVIEW"
    assert route(True, "send_alert", 6000, 0.99, POL).outcome == "REVIEW"
    assert route(True, "send_alert", 100, 0.5, POL).outcome == "REVIEW"
    assert route(True, "send_alert", 100, 0.99, POL, consistent=False).outcome == "REVIEW"


def test_property_i_no_material_autonomy():
    rng = np.random.default_rng(0)
    for _ in range(5000):
        a = rng.choice(A0 + OTHER)
        impact = float(rng.uniform(0, 20000))
        c = float(rng.uniform(0, 1))
        r = route(True, a, impact, c, POL, consistent=bool(rng.integers(0, 2)))
        if impact > POL.tau_impact_usd:
            assert r.outcome != "AUTO"


def test_property_ii_monotone_escalation():
    rng = np.random.default_rng(1)
    for _ in range(5000):
        a = rng.choice(A0 + OTHER)
        i1, c1 = float(rng.uniform(0, 12000)), float(rng.uniform(0, 1))
        i2, c2 = i1 + float(rng.uniform(0, 5000)), c1 * float(rng.uniform(0, 1))
        r1 = route(True, a, i1, c1, POL)
        r2 = route(True, a, i2, c2, POL)  # higher impact, lower confidence
        if r1.outcome != "AUTO":
            assert r2.outcome != "AUTO"


def test_pre_approved_set_is_respected():
    for a in OTHER:
        assert route(True, a, 1.0, 1.0, POL).outcome == "REVIEW"
    widened = PolicyConfig(auto_actions=tuple(A0 + ["stop_idle_resource"]))
    assert route(True, "stop_idle_resource", 1.0, 1.0, widened).outcome == "AUTO"
    assert route(True, "stop_idle_resource", 1e6, 1.0, widened).outcome == "REVIEW"
