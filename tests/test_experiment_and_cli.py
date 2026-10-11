import json
import subprocess
import sys
from pathlib import Path

import pytest

from gcsi.config import ExperimentConfig, LLMSettings
from gcsi.evaluation import run_experiment, write_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("exp")
    cfg = ExperimentConfig(families=("steady", "lumpy"), n_seeds=2, llm=LLMSettings(provider="mock"))
    res = run_experiment(cfg, out, progress=None)
    return cfg, res, out


def test_experiment_outputs_and_invariants(result):
    cfg, res, out = result
    for f in ("method_results.csv", "incident_decisions.csv", "llm_layer.csv", "manifest.json", "audit.jsonl"):
        assert (out / f).exists()
    m = res["methods"]
    assert set(m.method) == {"threshold_alert", "residual_alert", "agent_ungoverned", "agent_governed"}
    g = m[m.method == "agent_governed"]
    assert g.material_autonomy_violations.sum() == 0
    assert (m.saving_usd <= m.waste_total + 1e-6).all() and (m.waste_incurred >= -1e-6).all()
    # the governed agent never executes a non-pre-approved action without a human
    inc = res["incidents"]
    auto = inc[(inc.method == "agent_governed") & (inc.route == "AUTO")]
    assert set(auto.action) <= {"no_action", "recalculate_baseline", "send_alert"}
    # human-triage methods execute nothing autonomously
    assert m[m.method.isin(["threshold_alert", "residual_alert"])].auto_exec.sum() == 0
    man = json.loads((out / "manifest.json").read_text())
    assert man["llm_model"].startswith("mock") and man["live_llm_calls"] > 0


def test_experiment_is_reproducible(tmp_path):
    cfg = ExperimentConfig(families=("steady",), n_seeds=2, llm=LLMSettings(provider="mock"))
    a = run_experiment(cfg, tmp_path / "a", progress=None)["methods"]
    b = run_experiment(cfg, tmp_path / "b", progress=None)["methods"]
    assert a.equals(b)


def test_report_is_written_and_flags_mock(result):
    cfg, res, out = result
    p = write_report(res, cfg, out, sweeps=False)
    text = p.read_text()
    assert "Mock reasoning layer" in text and "E2. Decision outcomes" in text


def test_audit_log_is_valid_jsonl(result):
    _, _, out = result
    lines = (out / "audit.jsonl").read_text().strip().splitlines()
    assert all(json.loads(x)["kind"] for x in lines) and any('"kind": "decision"' in x for x in lines)


def test_cli_dry_run_and_prompt():
    r = subprocess.run([sys.executable, "-m", "gcsi.cli", "experiment", "--seeds", "1", "--families", "steady", "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""})
    assert r.returncode == 0 and '"calls"' in r.stdout
    r = subprocess.run([sys.executable, "-m", "gcsi.cli", "prompt", "--schema"], cwd=ROOT, capture_output=True, text=True,
                       env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""})
    assert r.returncode == 0 and "recommended_action" in r.stdout


def test_no_import_side_effects():
    code = ("import sys, gcsi, gcsi.agent, gcsi.llm, gcsi.ingest, gcsi.evaluation, gcsi.ui\n"
            "assert 'openai' not in sys.modules and 'gradio' not in sys.modules\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""})
    assert r.returncode == 0, r.stderr


def test_ui_builds_and_handlers_work():
    pytest.importorskip("gradio")
    from gcsi import ui

    demo = ui.build_app()
    fns = {getattr(b.fn, "__name__", None): b.fn for b in demo.fns.values()}
    table, pick, state, msg = fns["run_detection"]("steady", 1, 10, 5000, 0.8, "mock", "", "", "", 0.0)
    assert len(table) > 0 and state["decisions"]
