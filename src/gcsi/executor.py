"""Simulated execution. No cloud account is ever touched; the executor only records what would have been done.

AUTO objects are executed immediately. REVIEW objects wait for a named human approver; REJECT objects are blocked.
The model never calls the executor: execution is rule-based code that reads the routing outcome (control iv).
"""
from __future__ import annotations

from dataclasses import dataclass

from .governance import AuditLog, trail_entry
from .schema import ACTION_CATALOG, GovernanceObject


@dataclass
class ExecutionResult:
    object_id: str
    status: str  # SIMULATED_EXECUTED | PENDING_APPROVAL | BLOCKED | DECLINED
    action: str
    simulated: bool = True


def execute(obj: GovernanceObject, audit: AuditLog | None = None) -> ExecutionResult:
    if obj.routing == "AUTO":
        res = ExecutionResult(obj.object_id, "SIMULATED_EXECUTED", obj.action_class)
        obj.decision_trail.append(trail_entry("system", "SIMULATED_EXECUTED", f"auto action {obj.action_class}"))
    elif obj.routing == "REVIEW":
        res = ExecutionResult(obj.object_id, "PENDING_APPROVAL", obj.action_class)
    else:
        res = ExecutionResult(obj.object_id, "BLOCKED", obj.action_class)
    if audit:
        audit.write("execution", {"object_id": obj.object_id, "status": res.status, "action": res.action})
    return res


def human_decision(
    obj: GovernanceObject,
    approver: str,
    approve: bool,
    rationale: str = "",
    override_action: str | None = None,
    audit: AuditLog | None = None,
) -> ExecutionResult:
    """Record a named human decision on a REVIEW or REJECT object, then simulate the outcome."""
    if obj.routing == "AUTO":
        raise ValueError("AUTO objects need no human decision")
    if not approver.strip():
        raise ValueError("a named approver is required")
    action = obj.action_class
    if override_action:
        if override_action not in ACTION_CATALOG:
            raise ValueError(f"{override_action} is not in the action catalog")
        obj.decision_trail.append(trail_entry(approver, "OVERRIDE", f"{action} -> {override_action}: {rationale}"))
        action = override_action
        approve = True
    elif approve:
        obj.decision_trail.append(trail_entry(approver, "APPROVED", rationale))
    else:
        obj.decision_trail.append(trail_entry(approver, "DECLINED", rationale))
    status = "SIMULATED_EXECUTED" if approve else "DECLINED"
    if approve:
        obj.decision_trail.append(trail_entry("system", "SIMULATED_EXECUTED", f"approved action {action}"))
    res = ExecutionResult(obj.object_id, status, action)
    if audit:
        audit.write("human_decision", {"object_id": obj.object_id, "approver": approver, "status": status, "action": action})
    return res
