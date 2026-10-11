import numpy as np
import pandas as pd
import pytest

from gcsi import synth
from gcsi.anomaly import attach_evidence, build_incidents, residual_detector, threshold_detector
from gcsi.config import PolicyConfig


def test_generator_is_deterministic_and_labeled():
    a, b = synth.generate("steady", 5), synth.generate("steady", 5)
    pd.testing.assert_frame_equal(a.panel, b.panel)
    pd.testing.assert_frame_equal(a.events, b.events)
    assert len(a.events) == 9 and a.events.is_waste.sum() == 6
    assert a.panel.entity.nunique() == 24
    assert (a.panel.spend >= 0).all()
    assert not a.events.entity.duplicated().any()
    assert synth.generate("steady", 6).panel.spend.sum() != a.panel.spend.sum()


@pytest.mark.parametrize("family", list(synth.FAMILIES))
def test_families_run(family):
    ds = synth.generate(family, 3)
    assert ds.panel.shape[0] == 24 * 120
    assert ds.excess.excess.sum() == pytest.approx(ds.events.total_excess_usd.sum(), rel=1e-6)


def test_injected_waste_is_detected_by_both_detectors():
    ds = synth.generate("steady", 1)
    idle = ds.events[ds.events.kind == "idle_resource"].iloc[0]
    for f in (residual_detector, threshold_detector):
        inc = build_incidents(f(ds.panel), "x")
        hit = [i for i in inc if i.entity == idle.entity and pd.Timestamp(i.start) <= idle.end and pd.Timestamp(i.end) >= idle.start]
        assert hit, f.__name__


def test_no_lookahead_in_residual_detector():
    ds = synth.generate("volatile", 2)
    full = residual_detector(ds.panel)
    cut_date = ds.panel.date.min() + pd.Timedelta(days=80)
    part = residual_detector(ds.panel[ds.panel.date <= cut_date])
    a = full[full.date <= cut_date].sort_values(["entity", "date"]).reset_index(drop=True)
    b = part.sort_values(["entity", "date"]).reset_index(drop=True)
    np.testing.assert_allclose(a.z.to_numpy(), b.z.to_numpy(), equal_nan=True)
    assert (a.flag.to_numpy() == b.flag.to_numpy()).all()


def test_evidence_uses_only_data_up_to_detection_day():
    ds = synth.generate("steady", 1)
    d = residual_detector(ds.panel)
    incs = attach_evidence(build_incidents(d, "residual"), d, PolicyConfig())
    for i in incs:
        assert i.evidence["window"]["detect"] == i.detect
        last = pd.Timestamp(i.detect)
        assert len(i.evidence["recent_daily_spend_usd"]) <= 21
        g = d[(d.entity == i.entity) & (d.date <= last)].tail(21)
        assert i.evidence["recent_daily_spend_usd"][-1] == pytest.approx(round(float(g.spend.iloc[-1]), 2))


def test_usage_awareness_suppresses_benign_surge():
    ds = synth.generate("steady", 1)
    benign = ds.events[ds.events.kind == "benign_usage_surge"]
    with_u = residual_detector(ds.panel)
    no_u = residual_detector(ds.panel.assign(usage=np.nan))
    def n_flags(df):
        return sum(int(df[(df.entity == r.entity) & (df.date >= r.start) & (df.date <= r.end)].flag.sum()) for r in benign.itertuples())
    assert n_flags(with_u) < n_flags(no_u)
