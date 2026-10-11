#!/usr/bin/env python3
"""
Illustrative simulation and reference routing rule for:
"Agentic AI Decision Systems for Cloud Financial Governance" (Chopra).

Purpose
-------
1. Reproduce Tables 3, 4 and 5 of the manuscript from their stated inputs, so every
   number in the simulation can be checked by a reader.
2. Provide a reference specification of the bounded-autonomy routing rule (Section 3.1).

IMPORTANT: this is a transparent re-computation of an *illustrative* scenario model.
It uses assumed inputs (see Table 2 of the manuscript), not observed data, and it is
not the research prototype. Thresholds in route() are placeholders, not calibrated values.

Model
-----
Weekly idle-resource waste (USD) = compute cost per hour (USD) x idle hours per week.
Inputs are point values chosen inside the ranges documented in Table 2.
No other dependencies are required: python3 governance_simulation.py
"""
from dataclasses import dataclass

# ---------------------------------------------------------------- Table 4 inputs
@dataclass
class Firm:
    name: str
    rate: float          # compute cost, USD per hour
    idle_base: float     # idle hours per week, conventional (BI-supported) environment
    idle_agentic: float  # idle hours per week, agentic environment
    days_base: float     # time to decision, baseline
    days_agentic: float  # time to decision, agentic

FIRMS = [
    Firm("Small",   150, 20, 18, 5, 3),
    Firm("Medium",  500, 35, 30, 7, 4),
    Firm("Large",  1000, 50, 40, 10, 6),
]

def waste(rate, hours):
    return rate * hours

def table4():
    rows = []
    for f in FIRMS:
        wb, wa = waste(f.rate, f.idle_base), waste(f.rate, f.idle_agentic)
        rows.append((f.name, f.rate, f.idle_base, wb, f.idle_agentic, wa,
                     f.days_base, f.days_agentic, wb - wa, (wb - wa) / wb))
    return rows

# ---------------------------------------------------------------- Table 3 (one-at-a-time, +/-25%)
def table3(shock=0.25):
    m = FIRMS[1]
    out = {}
    for label, k in (("low", 1 - shock), ("base", 1.0), ("high", 1 + shock)):
        rate = m.rate * k
        out[label] = dict(
            rate=rate,
            waste_base=waste(rate, m.idle_base),
            waste_agentic=waste(rate, m.idle_agentic),
            reduction=waste(rate, m.idle_base - m.idle_agentic),
            days_base=m.days_base * k,
            days_agentic=m.days_agentic * k,
            idle_reduction=(m.idle_base - m.idle_agentic) * k,
        )
    # joint downside: compute cost -25% AND idle-hour reduction -25%
    out["joint_downside_reduction"] = (m.rate * (1 - shock)) * ((m.idle_base - m.idle_agentic) * (1 - shock))
    return out

# ---------------------------------------------------------------- Table 5 (medium firm, scenario ranges)
SCENARIOS = [
    # name, time-to-decision (days), idle hours/week (low, high)
    ("Manual data reporting",      "10-30", (35, 50)),
    ("Business intelligence",      "7-14",  (25, 35)),
    ("Agentic AI decision system", "2-6",   (10, 30)),  # 10-20 design target; 30 = conservative case used in Tables 3-4
]

def table5(rate=500):
    return [(n, d, lo, hi, rate * lo, rate * hi) for n, d, (lo, hi) in SCENARIOS]

# ---------------------------------------------------------------- Reference routing rule (Section 3.1)
AUTO, REVIEW, REJECT = "AUTO", "REVIEW", "REJECT"
AUTO_ACTIONS = {"recalculate_baseline", "send_alert"}   # pre-approved, reversible action classes

def route(action, impact_usd, confidence, schema_valid=True, rules_pass=True,
          tau_impact=5_000.0, tau_conf=0.80):
    """Bounded-autonomy routing rho(g). Thresholds are illustrative placeholders.
    - REJECT: governance object fails schema or business-rule validation
    - AUTO:   pre-approved action class AND impact <= tau_impact AND confidence >= tau_conf
    - REVIEW: everything else (human authorisation required before execution)
    """
    if not (schema_valid and rules_pass):
        return REJECT
    if action in AUTO_ACTIONS and abs(impact_usd) <= tau_impact and confidence >= tau_conf:
        return AUTO
    return REVIEW

def check_properties():
    """Properties that hold by construction (Section 3.1); asserted here as a sanity check."""
    for imp in (5_001, 50_000, 5_000_000):                       # P-a: no material action is automatic
        for conf in (0.0, 0.5, 0.99, 1.0):
            assert route("recalculate_baseline", imp, conf) != AUTO
    assert route("modify_commitment", 100, 0.99) == REVIEW        # P-b: non-pre-approved actions need review
    assert route("send_alert", 100, 0.79) == REVIEW               # P-c: monotone in confidence
    assert route("send_alert", 100, 0.80) == AUTO
    assert route("send_alert", 100, 0.99, schema_valid=False) == REJECT
    return True

# ---------------------------------------------------------------- report
def fmt(x):
    return f"{x:,.0f}" if abs(x - round(x)) < 1e-9 else f"{x:,.2f}"

if __name__ == "__main__":
    print("TABLE 3 - sensitivity, medium firm, one-at-a-time +/-25%")
    t3 = table3()
    for k in ("low", "base", "high"):
        r = t3[k]
        print(f"  {k:>4}: rate={fmt(r['rate'])}  waste_base={fmt(r['waste_base'])}  waste_agentic={fmt(r['waste_agentic'])}"
              f"  reduction={fmt(r['reduction'])}  days_base={fmt(r['days_base'])}  days_agentic={fmt(r['days_agentic'])}"
              f"  idle_reduction_hrs={fmt(r['idle_reduction'])}")
    print(f"  joint downside (rate -25% and idle-hour reduction -25%): weekly reduction = {fmt(t3['joint_downside_reduction'])}")
    print("\nTABLE 4 - firm-size simulation")
    for r in table4():
        print("  {} rate={} idle_base={} waste_base={} idle_agentic={} waste_agentic={} days {}->{} reduction=${} ({:.1%})"
              .format(r[0], fmt(r[1]), fmt(r[2]), fmt(r[3]), fmt(r[4]), fmt(r[5]), r[6], r[7], fmt(r[8]), r[9]))
    print("\nTABLE 5 - decision-architecture scenarios, medium firm @ $500/hr")
    for n, d, lo, hi, wl, wh in table5():
        print(f"  {n:<28} days {d:<6} idle {lo}-{hi} h/wk   weekly waste ${fmt(wl)} - ${fmt(wh)}")
    print("\nrouting-rule property checks:", "passed" if check_properties() else "FAILED")
