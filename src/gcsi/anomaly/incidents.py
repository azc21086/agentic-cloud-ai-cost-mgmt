"""Group confirmed alerts into incidents and build the evidence packet the reasoning layer receives."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..schema import INPUT_REFS, Incident


def _day(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def build_incidents(daily: pd.DataFrame, detector: str, gap_days: int = 1, tag: str = "run") -> list[Incident]:
    """One incident per streak of flagged days (gaps up to `gap_days` are bridged) that contains a confirmed alert.

    `start` is the first flagged day of the streak and `detect` the first confirmed day. Evidence for the incident is
    later built only from data up to `detect`.
    """
    out: list[Incident] = []
    for ent, g in daily.groupby("entity", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        idx = np.flatnonzero(g["flag"].to_numpy())
        if not len(idx):
            continue
        for grp in np.split(idx, np.flatnonzero(np.diff(idx) > gap_days + 1) + 1):
            i, last = int(grp[0]), int(grp[-1])
            seg = g.iloc[i : last + 1]
            alerts = np.flatnonzero(seg["alert"].to_numpy())
            if len(alerts):
                d = i + int(alerts[0])
                out.append(
                    Incident(
                        incident_id=f"{tag}:{ent}:{_day(g.loc[i, 'date'])}",
                        entity=ent,
                        start=_day(g.loc[i, "date"]),
                        detect=_day(g.loc[d, "date"]),
                        end=_day(g.loc[last, "date"]),
                        detector=detector,
                    )
                )
    return out


def attach_evidence(
    incidents: list[Incident], daily: pd.DataFrame, policy, baseline_days: int = 14, history_days: int = 21
) -> list[Incident]:
    """Fill `incident.evidence` using data up to and including the detection day only."""
    by_ent = {e: g.sort_values("date").reset_index(drop=True) for e, g in daily.groupby("entity", sort=False)}
    for inc in incidents:
        g = by_ent[inc.entity]
        d0, d1 = pd.Timestamp(inc.start), pd.Timestamp(inc.detect)
        seg = g[(g["date"] >= d0) & (g["date"] <= d1)]
        pre = g[(g["date"] < d0)].tail(baseline_days)
        hist = g[(g["date"] <= d1)].tail(history_days)
        obs = float(seg["spend"].mean())
        exp = float(seg["expected"].mean())
        exc = float(seg["excess"].mean())
        base = float(pre["spend"].mean()) if len(pre) else float("nan")
        u_seg, u_pre = seg["usage"].mean(), pre["usage"].mean() if len(pre) else np.nan
        spend_chg = (obs - base) / base if base and base > 0 else float("nan")
        usage_chg = (u_seg - u_pre) / u_pre if (not np.isnan(u_seg) and u_pre and u_pre > 0) else None
        if usage_chg is None:
            share = None  # usage not available
        elif not np.isnan(spend_chg) and spend_chg > 0.05:
            share = float(np.clip(usage_chg / spend_chg, 0.0, 1.0))
        else:
            share = 0.0
        ex = seg["excess"].to_numpy(float)
        if len(seg) == 1:
            shape = "spike"
        elif len(ex) >= 2 and np.all(np.diff(ex) > 0) and ex[-1] >= 1.3 * ex[0]:
            shape = "ramp"
        else:
            shape = "step"
        z = float(np.nanmean(seg["z"].to_numpy(float)))
        inc.evidence = {
            "incident_id": inc.incident_id,
            "entity": inc.entity,
            "window": {"start": inc.start, "detect": inc.detect},
            "persistence_days": int(len(seg)),
            "observed_daily_spend_usd": round(obs, 2),
            "expected_daily_spend_usd": round(exp, 2),
            "excess_daily_usd": round(exc, 2),
            "baseline_daily_spend_usd": None if np.isnan(base) else round(base, 2),
            "spend_change_pct": None if np.isnan(spend_chg) else round(100 * spend_chg, 1),
            "usage_change_pct": None if usage_chg is None else round(100 * usage_chg, 1),
            "usage_explained_share": None if share is None else round(share, 2),
            "z_score": round(z, 2),
            "shape": shape,
            "impact_measured_usd_per_week": round(max(exc, 0.0) * policy.period_days, 2),
            "recent_daily_spend_usd": [round(float(v), 2) for v in hist["spend"].to_numpy()],
            "input_refs": list(INPUT_REFS),
            "policy": {
                "tau_impact_usd_per_week": policy.tau_impact_usd,
                "tau_conf": policy.tau_conf,
                "pre_approved_actions": list(policy.auto_actions),
            },
        }
    return incidents
