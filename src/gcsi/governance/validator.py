"""Schema and business-rule validation of model output (controls i and ii). Strict: output is never repaired."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from ..config import PolicyConfig
from ..schema import ACTION_CATALOG, INPUT_REFS, REQUIRED_FIELDS

IMPACT_FLOOR_USD = 100.0  # below this per-week size, ratio checks on the impact are not meaningful


@dataclass
class Validation:
    ok: bool
    errors: list = field(default_factory=list)
    record: dict | None = None  # normalized record when ok
    n_unsupported: int = 0  # causal factors citing an input the model was not given


def parse_json_strict(text: str):
    """Return the parsed object or None. No fence stripping, no truncation repair."""
    try:
        obj = json.loads(text)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_record(rec: dict | None, evidence: dict, policy: PolicyConfig) -> Validation:
    if rec is None:
        return Validation(False, ["NOT_VALID_JSON_OBJECT"])
    errors: list[str] = []
    for f in REQUIRED_FIELDS:
        if f not in rec:
            errors.append(f"MISSING_FIELD:{f}")
    if errors:
        return Validation(False, errors)

    if not isinstance(rec["event"], str) or not rec["event"].strip():
        errors.append("BAD_EVENT")

    unsupported = 0
    cf = rec["causal_factors"]
    if not isinstance(cf, list) or not cf:
        errors.append("BAD_CAUSAL_FACTORS")
    else:
        total = 0.0
        for item in cf:
            if not (isinstance(item, dict) and isinstance(item.get("factor"), str) and isinstance(item.get("evidence_ref"), str) and _num(item.get("share")) and 0 <= item["share"] <= 1):
                errors.append("BAD_CAUSAL_FACTOR_ITEM")
                break
            total += float(item["share"])
            if item["evidence_ref"] not in evidence.get("input_refs", INPUT_REFS):
                unsupported += 1
        else:
            if abs(total - 1.0) > policy.share_sum_tolerance:
                errors.append("SHARES_DO_NOT_SUM_TO_ONE")

    fi = rec["financial_impact"]
    value = None
    if not (isinstance(fi, dict) and all(_num(fi.get(k)) and fi[k] >= 0 for k in ("value_usd_per_week", "low", "high"))):
        errors.append("BAD_FINANCIAL_IMPACT")
    else:
        value = float(fi["value_usd_per_week"])
        if not (fi["low"] - 1e-6 <= value <= fi["high"] + 1e-6):
            errors.append("IMPACT_OUTSIDE_OWN_INTERVAL")

    ra = rec["recommended_action"]
    if not (isinstance(ra, dict) and isinstance(ra.get("class"), str)):
        errors.append("BAD_ACTION")
    elif ra["class"] not in ACTION_CATALOG:
        errors.append("ACTION_NOT_IN_CATALOG")
    elif "params" in ra and not isinstance(ra["params"], dict):
        errors.append("BAD_ACTION_PARAMS")

    c = rec["confidence"]
    if not (_num(c) and 0.0 <= c <= 1.0):
        errors.append("BAD_CONFIDENCE")

    # Business rule: the stated impact must be grounded in the measured deviation.
    measured = evidence.get("impact_measured_usd_per_week")
    if value is not None and measured is not None:
        f = policy.impact_ratio_tolerance
        within_ratio = measured > 0 and (measured / f) <= value <= (measured * f)
        within_floor = abs(value - measured) <= IMPACT_FLOOR_USD
        if not (within_ratio or within_floor):
            errors.append("IMPACT_NOT_GROUNDED")

    if errors:
        return Validation(False, errors, n_unsupported=unsupported)
    norm = {
        "event": rec["event"].strip(),
        "causal_factors": [dict(x) for x in cf],
        "financial_impact": {k: float(fi[k]) for k in ("value_usd_per_week", "low", "high")},
        "recommended_action": {"class": ra["class"], "params": dict(ra.get("params", {}))},
        "confidence": float(c),
        "rationale": str(rec.get("rationale", "")),
    }
    return Validation(True, [], norm, unsupported)
