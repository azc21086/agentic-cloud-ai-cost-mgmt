import copy
import json

from gcsi.config import PolicyConfig
from gcsi.governance import parse_json_strict, validate_record

POL = PolicyConfig()
EV = {"entity": "A|B|C", "impact_measured_usd_per_week": 2000.0, "input_refs": ["spend_series", "usage_series", "forecast_interval", "policy"]}
GOOD = {
    "event": "x",
    "causal_factors": [
        {"factor": "f1", "evidence_ref": "usage_series", "share": 0.6},
        {"factor": "f2", "evidence_ref": "forecast_interval", "share": 0.4},
    ],
    "financial_impact": {"value_usd_per_week": 2000.0, "low": 1600.0, "high": 2400.0},
    "recommended_action": {"class": "stop_idle_resource", "params": {}},
    "confidence": 0.8,
}


def check(mut, code):
    rec = copy.deepcopy(GOOD)
    mut(rec)
    v = validate_record(rec, EV, POL)
    assert not v.ok and any(code in e for e in v.errors), v.errors


def test_good_record_passes():
    v = validate_record(GOOD, EV, POL)
    assert v.ok and v.n_unsupported == 0


def test_error_paths():
    check(lambda r: r.pop("confidence"), "MISSING_FIELD")
    check(lambda r: r["recommended_action"].update({"class": "delete_everything"}), "ACTION_NOT_IN_CATALOG")
    check(lambda r: r.update({"confidence": 1.5}), "BAD_CONFIDENCE")
    check(lambda r: r["financial_impact"].update({"value_usd_per_week": 20000.0, "high": 30000.0}), "IMPACT_NOT_GROUNDED")
    check(lambda r: r["financial_impact"].update({"low": 2100.0}), "IMPACT_OUTSIDE_OWN_INTERVAL")
    check(lambda r: r["causal_factors"][0].update({"share": 0.1}), "SHARES_DO_NOT_SUM_TO_ONE")
    check(lambda r: r.update({"causal_factors": []}), "BAD_CAUSAL_FACTORS")


def test_unsupported_factor_is_flagged_not_rejected():
    rec = copy.deepcopy(GOOD)
    rec["causal_factors"][1]["evidence_ref"] = "vendor_price_list"
    v = validate_record(rec, EV, POL)
    assert v.ok and v.n_unsupported == 1


def test_parser_is_strict_and_never_repairs():
    assert parse_json_strict(json.dumps(GOOD)) is not None
    assert parse_json_strict("```json\n" + json.dumps(GOOD) + "\n```") is None
    assert parse_json_strict(json.dumps(GOOD)[:-5]) is None
    assert parse_json_strict("[1,2]") is None
    assert validate_record(None, EV, POL).errors == ["NOT_VALID_JSON_OBJECT"]


def test_small_impacts_use_absolute_floor():
    ev = {**EV, "impact_measured_usd_per_week": 10.0}
    rec = copy.deepcopy(GOOD)
    rec["financial_impact"] = {"value_usd_per_week": 80.0, "low": 60.0, "high": 100.0}
    assert validate_record(rec, ev, POL).ok
