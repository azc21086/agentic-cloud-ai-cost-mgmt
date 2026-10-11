"""Routing function rho (paper Section 3.1).

  REJECT  if the object fails schema or business-rule validation
  AUTO    if valid, action in A0, |I| <= tau_I, c >= tau_c (and repeated evaluations agree, control iii)
  REVIEW  otherwise: nothing is executed until a named human approver records a decision

Properties that hold by construction and are tested in tests/test_router.py:
  (i)   no material autonomy: |I| > tau_I is never AUTO
  (ii)  monotone escalation: lowering c or raising |I| never moves an object from REVIEW or REJECT to AUTO
  (iii) complete trail: every routing outcome is written to the object's decision trail and the audit log
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import PolicyConfig


@dataclass
class RouteResult:
    outcome: str
    reason_codes: list = field(default_factory=list)


def route(
    valid: bool, action: str, impact_usd: float, confidence: float, policy: PolicyConfig, consistent: bool = True
) -> RouteResult:
    if not valid:
        return RouteResult("REJECT", ["VALIDATION_FAILED"])
    reasons = []
    if action not in policy.auto_actions:
        reasons.append("ACTION_NOT_PRE_APPROVED")
    if abs(impact_usd) > policy.tau_impact_usd:
        reasons.append("IMPACT_ABOVE_MATERIALITY")
    if confidence < policy.tau_conf:
        reasons.append("CONFIDENCE_BELOW_THRESHOLD")
    if not consistent:
        reasons.append("INCONSISTENT_REPEATS")
    if reasons:
        return RouteResult("REVIEW", reasons)
    return RouteResult("AUTO", ["ALL_AUTO_CONDITIONS_MET"])
