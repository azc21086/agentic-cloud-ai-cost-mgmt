"""Gradio interface (the paper's Figure 4). Import-safe: nothing runs until `build_app()` or `launch()` is called.

Tabs: Ask & Visualize, Forecast, Anomalies & Governance. Every language-model feature works with no key in mock mode.
The key typed here is used for the current request only and is never stored, logged or cached.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from . import forecast as fc
from . import ingest, insights, synth
from .agent import decide
from .anomaly import attach_evidence, build_incidents, residual_detector
from .config import LLMSettings, PolicyConfig, ResidualConfig
from .executor import execute, human_decision
from .governance import AuditLog
from .llm import make_client
from .schema import ACTION_CATALOG

DEFAULT_DATA = Path(os.environ.get("GCSI_DATA_DIR") or Path(__file__).resolve().parents[2] / "data" / "sample")
SAMPLE_RESIDUAL = ResidualConfig(min_abs_excess_usd=0.5, scale_floor_abs=0.2)


def _client(provider: str, model: str, base_url: str, api_key: str, fault_rate: float):
    st = LLMSettings(provider=provider, model=model or "gpt-4o-mini", base_url=base_url or None, mock_fault_rate=fault_rate)
    return make_client(st, api_key=api_key or None), st


def _plot_entity(daily: pd.DataFrame, entity: str, inc=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = daily[daily["entity"] == entity].sort_values("date")
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(g["date"], g["spend"], label="Spend", color="#3b6ea5")
    ax.plot(g["date"], g["expected"], label="Forecast", color="#999", linestyle="--")
    f = g[g["flag"]]
    ax.scatter(f["date"], f["spend"], color="#c0392b", s=14, label="Flagged day", zorder=3)
    if inc is not None:
        ax.axvline(pd.Timestamp(inc.detect), color="#c0392b", alpha=0.4)
    ax.set_title(entity)
    ax.set_ylabel("USD per day")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def build_app():
    import gradio as gr

    sample_tables = {}

    def sample():
        if not sample_tables:
            t = ingest.load_sample_tables(DEFAULT_DATA)
            sample_tables["enriched"] = ingest.build_enriched(t)
            sample_tables["panel"] = ingest.build_entity_panel(t)
        return sample_tables

    # ----------------------------------------------------------------- tab 1
    def on_load():
        df = sample()["enriched"]
        return insights.render_precomputed(insights.precomputed(df))

    def run_query(question, provider, model, base_url, api_key, fault_rate):
        df = sample()["enriched"]
        kind = insights.classify(question or "")
        facts = insights.facts_for(df, kind)
        try:
            llm, _ = _client(provider, model, base_url, api_key, fault_rate) if provider != "mock" else (None, None)
        except Exception as e:
            raise gr.Error(str(e))
        return insights.make_chart(df, kind), insights.narrate(question or "", facts, llm)

    # ----------------------------------------------------------------- tab 2
    def forecast_view(view, product):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        panel = sample()["panel"]
        fig, ax = plt.subplots(figsize=(7, 3.8))
        if view.startswith("Model quality"):
            bt = fc.backtest_table(panel)
            bt = bt.dropna(subset=["wape_model"])
            if bt.empty:
                ax.text(0.5, 0.5, "Not enough history for a rolling-origin backtest", ha="center")
            else:
                x = range(len(bt))
                w = 0.27
                ax.bar([i - w for i in x], bt["wape_model"], w, label="Usage regression")
                ax.bar(list(x), bt["wape_seasonal_naive"], w, label="Seasonal naive")
                ax.bar([i + w for i in x], bt["wape_trailing_mean"], w, label="14-day mean")
                ax.set_xticks(list(x))
                ax.set_xticklabels(bt["product"])
                ax.set_ylabel("WAPE (lower is better)")
                ax.set_title("Rolling-origin backtest, 7-day horizon")
                ax.legend()
            note = bt.round(3).to_string(index=False)
        else:
            s = fc.trim_leading_zeros(fc.product_series(panel, product))
            if len(s) < 21:
                ax.text(0.5, 0.5, "Not enough history to forecast", ha="center")
                note = ""
            else:
                f = fc.forecast_future(s, 30)
                ax.plot(s["date"], s["spend"], label="Actual")
                ax.plot(f["date"], f["yhat"], label="Forecast", color="#e67e22")
                ax.fill_between(f["date"], f["lo"], f["hi"], alpha=0.2, color="#e67e22", label="80% interval")
                ax.set_title(f"{product}: 30-day forecast")
                ax.set_ylabel("USD per day")
                ax.legend()
                note = "Future usage is a linear projection of the last 28 days. History before first spend is dropped."
        ax.grid(alpha=0.25)
        fig.autofmt_xdate()
        fig.tight_layout()
        return fig, note

    # ----------------------------------------------------------------- tab 3
    def run_detection(source, seed, max_inc, tau_i, tau_c, provider, model, base_url, api_key, fault_rate):
        try:
            llm, st = _client(provider, model, base_url, api_key, fault_rate)
        except Exception as e:
            raise gr.Error(str(e))
        if source == "Prototype sample CSVs":
            panel = sample()["panel"]
            rcfg = SAMPLE_RESIDUAL  # the sample is tiny (cents per entity-day), so dollar floors are scaled down
        else:
            panel = synth.generate(source, int(seed)).panel
            rcfg = ResidualConfig()
        pol = PolicyConfig(tau_impact_usd=float(tau_i), tau_conf=float(tau_c))
        daily = residual_detector(panel, rcfg)
        incs = attach_evidence(build_incidents(daily, "residual", tag="ui"), daily, pol)[: int(max_inc)]
        audit = AuditLog()
        decisions = {}
        for inc in incs:
            d = decide(inc, llm, pol, st, audit, run_id="ui")
            execute(d.obj, audit)
            decisions[inc.incident_id] = d
        rows = [
            {"incident": i.incident_id, "entity": i.entity, "start": i.start, "detected": i.detect,
             "route": decisions[i.incident_id].obj.routing, "action": decisions[i.incident_id].obj.action_class,
             "impact_usd_per_week": round(decisions[i.incident_id].obj.financial_impact.get("routing_value_usd_per_week", 0.0), 0),
             "confidence": decisions[i.incident_id].obj.confidence}
            for i in incs
        ]
        state = {"incs": {i.incident_id: i for i in incs}, "decisions": decisions, "daily": daily, "audit": audit}
        ids = [i.incident_id for i in incs]
        msg = f"{len(incs)} incident(s). AUTO objects were executed in simulation only; REVIEW objects wait for a named approver."
        errs = [d.llm_meta["error"] for d in decisions.values() if d.llm_meta.get("error")]
        if errs:
            msg += f"\n\n**Model call failed on {len(errs)} incident(s); those show as REJECT.** First error: `{errs[0]}`"
        return pd.DataFrame(rows), gr.update(choices=ids, value=ids[0] if ids else None), state, msg

    def show_incident(incident_id, state):
        if not state or incident_id not in state["decisions"]:
            return None, {}, ""
        d = state["decisions"][incident_id]
        inc = state["incs"][incident_id]
        fig = _plot_entity(state["daily"], inc.entity, inc)
        return fig, d.obj.to_dict(), f"Routing: {d.obj.routing} ({', '.join(d.obj.reason_codes)})"

    def record_decision(incident_id, approver, choice, override, rationale, state):
        if not state or incident_id not in state["decisions"]:
            raise gr.Error("run detection first")
        obj = state["decisions"][incident_id].obj
        try:
            human_decision(
                obj, approver or "", choice == "Approve", rationale or "",
                override_action=override if choice == "Override with" else None, audit=state["audit"],
            )
        except ValueError as e:
            raise gr.Error(str(e))
        return obj.to_dict(), "Decision recorded in the object's trail (simulation only)."

    def export_audit(state):
        if not state:
            raise gr.Error("run detection first")
        p = Path(tempfile.mkdtemp()) / "audit.jsonl"
        p.write_text("\n".join(json.dumps(e, default=str) for e in state["audit"].events))
        return str(p)

    # ----------------------------------------------------------------- layout
    with gr.Blocks(title="GCSI: Generative Cloud Spend Intelligence") as demo:
        gr.Markdown("## GCSI: governed cloud spend intelligence\nAll agentic actions are simulated. No cloud account is touched.")
        with gr.Accordion("Reasoning layer settings", open=False):
            provider = gr.Radio(["mock", "openai"], value="mock", label="Provider (openai means any OpenAI-compatible endpoint)")
            model = gr.Textbox(value="gpt-4o-mini", label="Model")
            base_url = gr.Textbox(value="", label="Base URL (optional)")
            api_key = gr.Textbox(value="", label="API key (used for this request only, never stored)", type="password")
            fault_rate = gr.Slider(0, 0.5, value=0.15, step=0.05, label="Mock only: share of responses corrupted on purpose")
        with gr.Tabs():
            with gr.Tab("Ask & Visualize"):
                pre = gr.Textbox(label="Precomputed insights", lines=14, interactive=False)
                q = gr.Textbox(label="Ask a question (for example: spend by cloud provider, ROI by product, spend by region)")
                go = gr.Button("Run")
                chart = gr.Plot(label="Chart")
                ans = gr.Textbox(label="Answer", lines=8, interactive=False)
                go.click(run_query, [q, provider, model, base_url, api_key, fault_rate], [chart, ans])
                demo.load(on_load, None, pre)
            with gr.Tab("Forecast"):
                view = gr.Radio(["Model quality (backtest)", "Forecast by product"], value="Model quality (backtest)", label="View")
                prod = gr.Dropdown(["Alpha", "Beta"], value="Alpha", label="Product")
                fplot = gr.Plot()
                fnote = gr.Textbox(label="Notes", lines=5, interactive=False)
                view.change(forecast_view, [view, prod], [fplot, fnote])
                prod.change(forecast_view, [view, prod], [fplot, fnote])
            with gr.Tab("Anomalies & Governance"):
                with gr.Row():
                    source = gr.Dropdown(["Prototype sample CSVs", *synth.FAMILIES], value="steady", label="Data")
                    seed = gr.Number(value=1, label="Seed (synthetic only)", precision=0)
                    max_inc = gr.Slider(5, 100, value=25, step=5, label="Max incidents to evaluate")
                with gr.Row():
                    tau_i = gr.Number(value=5000, label="Materiality tau_I (USD per week)")
                    tau_c = gr.Slider(0.5, 0.99, value=0.8, step=0.01, label="Confidence threshold tau_c")
                run = gr.Button("Detect and route")
                msg = gr.Markdown()
                table = gr.Dataframe(label="Incidents and routing", interactive=False)
                state = gr.State()
                pick = gr.Dropdown(label="Incident", choices=[])
                route_note = gr.Markdown()
                eplot = gr.Plot()
                obj = gr.JSON(label="Governance object")
                with gr.Row():
                    approver = gr.Textbox(label="Approver (named)")
                    choice = gr.Radio(["Approve", "Decline", "Override with"], value="Approve", label="Decision")
                    override = gr.Dropdown(list(ACTION_CATALOG), value="stop_idle_resource", label="Override action")
                rationale = gr.Textbox(label="Rationale")
                rec = gr.Button("Record decision")
                rec_msg = gr.Markdown()
                exp = gr.Button("Export audit log")
                file = gr.File(label="Audit log (JSONL)")
                run.click(run_detection, [source, seed, max_inc, tau_i, tau_c, provider, model, base_url, api_key, fault_rate],
                          [table, pick, state, msg])
                pick.change(show_incident, [pick, state], [eplot, obj, route_note])
                rec.click(record_decision, [pick, approver, choice, override, rationale, state], [obj, rec_msg])
                exp.click(export_audit, [state], [file])
    return demo


def launch(**kw):
    build_app().launch(**kw)
