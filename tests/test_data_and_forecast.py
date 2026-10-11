from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gcsi import forecast as fc
from gcsi import ingest
from gcsi.evaluation.economics import action_effect, waste_incurred

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"


def test_sample_loaders():
    t = ingest.load_sample_tables(DATA)
    panel = ingest.build_entity_panel(t)
    assert panel.entity.nunique() == 24 and panel.date.nunique() == 90
    assert panel.spend.sum() == pytest.approx(4269.06, abs=0.01)
    e = ingest.build_enriched(t)
    assert not np.isinf(e.select_dtypes("number").to_numpy()).any()
    assert e.groupby("REGION").TOTAL_SPEND.sum()["LATAM"] == pytest.approx(1251.30, abs=0.01)


def test_densify_fills_missing_days_with_zero():
    p = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-01-03"]), "entity": "a", "spend": [5.0, 7.0]})
    d = ingest.densify(p)
    assert len(d) == 3 and d.spend.tolist() == [5.0, 0.0, 7.0]


def test_focus_loader_filters_to_usage_charges(tmp_path):
    f = tmp_path / "f.csv"
    pd.DataFrame({
        "ChargePeriodStart": ["2024-09-01T00:00:00Z"] * 3 + ["2024-09-02T00:00:00Z"],
        "EffectiveCost": [10.0, 5.0, 100.0, 12.0], "ProviderName": ["AWS"] * 4,
        "ServiceCategory": ["Compute"] * 4, "ServiceName": ["EC2"] * 4,
        "ChargeCategory": ["Usage", "Usage", "Purchase", "Usage"], "ConsumedQuantity": [1, 2, 3, 4],
    }).to_csv(f, index=False)
    p = ingest.load_any(f)
    assert p.spend.tolist() == [15.0, 12.0] and p.usage.tolist() == [3.0, 4.0]


def test_validate_rejects_duplicates():
    p = pd.DataFrame({"date": pd.to_datetime(["2025-01-01"] * 2), "entity": "a", "spend": [1.0, 2.0]})
    with pytest.raises(ValueError):
        ingest.validate_panel(p)


def _series(n=90, seed=0):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2025-01-01", periods=n)
    u = 1000 + 5 * np.arange(n) + rng.normal(0, 20, n)
    return pd.DataFrame({"date": d, "usage": u, "spend": 50 + 0.2 * u + rng.normal(0, 2, n)})


def test_forecast_has_no_leakage():
    s = _series()
    X_full = fc.design_matrix(s.date.to_numpy(), s.usage.to_numpy(), s.date.iloc[0])
    t = 60
    f1 = fc.fit_ols(X_full[:t], s.spend.to_numpy()[:t])
    s2 = s.copy()
    s2.loc[t:, "spend"] += 1000.0  # change the future
    f2 = fc.fit_ols(X_full[:t], s2.spend.to_numpy()[:t])
    np.testing.assert_allclose(f1.beta, f2.beta)


def test_backtest_beats_naive_on_usage_driven_data_and_interval_is_sane():
    r = fc.rolling_origin_backtest(_series())
    assert r["wape_model"] < r["wape_seasonal_naive"] and r["wape_model"] < r["wape_trailing_mean"]
    assert 0.6 <= r["interval_coverage"] <= 1.0
    f = fc.forecast_future(_series(), 14)
    assert len(f) == 14 and (f.lo <= f.yhat).all() and (f.yhat <= f.hi).all()


def test_waste_incurred_and_effects():
    ex = np.array([100.0, 100.0, 100.0])  # event days 10, 11, 12
    assert waste_incurred(ex, 10, float("inf")) == 300.0
    assert waste_incurred(ex, 10, 10.0) == 0.0
    assert waste_incurred(ex, 10, 11.5) == pytest.approx(150.0)
    assert waste_incurred(ex, 10, 20.0) == 300.0
    waste = {"is_waste": True, "valid_actions": "stop_idle_resource|rightsize_instance"}
    benign = {"is_waste": False, "valid_actions": "recalculate_baseline|no_action"}
    assert action_effect(waste, "stop_idle_resource") == "fix"
    assert action_effect(waste, "recalculate_baseline") == "mask"
    assert action_effect(waste, "send_alert") == "alert"
    assert action_effect(waste, "purchase_commitment") == "misdirect"
    assert action_effect(benign, "recalculate_baseline") == "ok"
    assert action_effect(benign, "stop_idle_resource") == "disrupt"
    assert action_effect(None, "apply_budget_cap") == "disrupt"
