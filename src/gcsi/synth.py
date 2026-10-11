"""Synthetic cloud-spend generator with labeled, injected events.

Structure mirrors the prototype sample (2 products x 3 providers x 4 spend categories = 24 entities, daily grain) but
runs at a realistic dollar scale. Four independent scenario families differ in noise, growth and sparsity.

Each entity has a usage driver and a spend series that is a fixed part plus a usage-proportional part. Events:
  idle_resource      waste   constant extra spend, usage unchanged
  runaway_job        waste   extra spend that ramps up, usage unchanged
  egress_spike       waste   one or two days of very large extra spend
  benign_usage_surge benign  usage rises and spend rises with it (a launch or seasonal peak); not waste
Ground truth (events table and a per-day excess table) is returned for evaluation. Nothing here is real data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import make_entity
from .schema import CAUSE_VALID_ACTIONS, WASTE_CAUSES

PRODUCTS = ("Alpha", "Beta")
PROVIDERS = ("AWS", "Azure", "Google Cloud")
CATEGORIES = ("compute", "storage", "network", "observability")

FAMILIES: dict[str, dict] = {
    # noise: multiplicative daily noise on spend; usage_noise: measurement noise on observed usage
    "steady": dict(noise=0.05, usage_noise=0.04, trend=0.0005, weekly=0.08, lumpy=False),
    "volatile": dict(noise=0.16, usage_noise=0.12, trend=0.0005, weekly=0.15, lumpy=False),
    "growth": dict(noise=0.08, usage_noise=0.06, trend=0.008, weekly=0.10, lumpy=False),
    "lumpy": dict(noise=0.20, usage_noise=0.10, trend=0.004, weekly=0.10, lumpy=True),
}


@dataclass
class SynthDataset:
    family: str
    seed: int
    panel: pd.DataFrame  # canonical panel (observed)
    events: pd.DataFrame  # one row per injected event
    excess: pd.DataFrame  # date, entity, excess (injected extra spend per day, waste events only)
    meta: dict = field(default_factory=dict)


def _smooth_ramp(n: int, k: int = 3) -> np.ndarray:
    r = np.ones(n)
    for i in range(min(k, n)):
        r[i] = (i + 1) / (k + 1)
    return r


def generate(
    family: str,
    seed: int,
    n_days: int = 120,
    n_waste: int = 6,
    n_benign: int = 3,
    start_date: str = "2025-01-01",
    first_event_day: int = 45,
) -> SynthDataset:
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family}; choose from {list(FAMILIES)}")
    fam = FAMILIES[family]
    rng = np.random.default_rng([seed, list(FAMILIES).index(family) + 1])
    dates = pd.date_range(start_date, periods=n_days, freq="D")
    t = np.arange(n_days)
    dow = dates.dayofweek.to_numpy()
    weekly = 1.0 + fam["weekly"] * np.where(dow >= 5, -1.0, 0.4)

    ents = [(p, pr, c) for p in PRODUCTS for pr in PROVIDERS for c in CATEGORIES]
    n_ent = len(ents)
    base = np.clip(rng.lognormal(np.log(250), 0.8, n_ent), 40, 3000)
    fixed_share = 0.30
    u0 = rng.lognormal(np.log(1e5), 0.5, n_ent)
    growth = 1.0 + fam["trend"] * t[None, :] * rng.uniform(0.5, 1.5, (n_ent, 1))
    # usage-driven benign surges modify the true usage multiplier
    usage_mult = np.ones((n_ent, n_days))

    onset = np.zeros(n_ent, dtype=int)
    if fam["lumpy"]:
        onset = rng.integers(5, 40, n_ent)

    # ---- choose events on distinct entities, after the burn-in period
    n_ev = n_waste + n_benign
    chosen = rng.choice(n_ent, size=min(n_ev, n_ent), replace=False)
    kinds = (
        list(rng.choice(["idle_resource", "runaway_job", "egress_spike"], size=n_waste, p=[0.4, 0.35, 0.25]))
        + ["benign_usage_surge"] * n_benign
    )
    rng.shuffle(kinds)
    ev_rows, excess_add = [], np.zeros((n_ent, n_days))
    for k, (e, kind) in enumerate(zip(chosen, kinds)):
        lo = max(first_event_day, onset[e] + 35 if fam["lumpy"] else first_event_day)
        hi = n_days - 12
        if lo >= hi:
            lo = max(first_event_day, hi - 5)
        s = int(rng.integers(lo, hi))
        if kind == "idle_resource":
            dur = int(rng.integers(8, 26))
            amt = max(60.0, base[e] * rng.uniform(0.5, 2.0))
            prof = np.full(dur, amt)
        elif kind == "runaway_job":
            dur = int(rng.integers(7, 21))
            peak = max(90.0, base[e] * rng.uniform(1.0, 4.0))
            prof = np.linspace(0.15 * peak, peak, dur)
        elif kind == "egress_spike":
            dur = int(rng.integers(1, 3))
            amt = max(150.0, base[e] * rng.uniform(2.0, 6.0))
            prof = np.full(dur, amt)
        else:
            dur = int(rng.integers(10, 31))
            mult = rng.uniform(1.5, 2.5)
            prof = None
        end = min(s + dur - 1, n_days - 1)
        dur = end - s + 1
        if kind in WASTE_CAUSES:
            excess_add[e, s : end + 1] += prof[:dur]
            total = float(prof[:dur].sum())
            weekly_impact = total * 7.0 / max(dur, 7)
        else:
            usage_mult[e, s : end + 1] *= 1.0 + (mult - 1.0) * _smooth_ramp(dur)
            total, weekly_impact = 0.0, 0.0
        ev_rows.append(
            dict(
                event_id=f"{family}-{seed}-{k}",
                entity=make_entity(*ents[e]),
                kind=kind,
                is_waste=kind in WASTE_CAUSES,
                start=dates[s],
                end=dates[end],
                start_idx=s,
                end_idx=end,
                duration_days=dur,
                total_excess_usd=round(total, 2),
                true_weekly_impact_usd=round(weekly_impact, 2),
                valid_actions="|".join(CAUSE_VALID_ACTIONS[kind]),
            )
        )

    # ---- build series
    u_true = u0[:, None] * growth * weekly[None, :] * usage_mult * rng.lognormal(0, 0.03, (n_ent, n_days))
    c = (base * (1 - fixed_share) / u0)[:, None]
    spend_clean = (base * fixed_share)[:, None] * growth * weekly[None, :] + c * u_true
    if fam["lumpy"]:
        ramp = np.clip((t[None, :] - onset[:, None]) / 20.0, 0.0, 1.0)
        spend_clean = spend_clean * ramp
        u_true = u_true * ramp
    noise = rng.normal(0.0, fam["noise"], (n_ent, n_days))
    spend = np.clip(spend_clean * (1.0 + noise) + excess_add, 0.0, None)
    u_obs = np.clip(u_true * (1.0 + rng.normal(0.0, fam["usage_noise"], (n_ent, n_days))), 0.0, None)

    rows, ex_rows = [], []
    for e, (p, pr, cat) in enumerate(ents):
        ent = make_entity(p, pr, cat)
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "entity": ent,
                    "product": p,
                    "provider": pr,
                    "category": cat,
                    "spend": np.round(spend[e], 2),
                    "usage": np.round(u_obs[e], 1),
                }
            )
        )
        if excess_add[e].any():
            ex_rows.append(pd.DataFrame({"date": dates, "entity": ent, "excess": excess_add[e]}))
    panel = pd.concat(rows, ignore_index=True)
    events = pd.DataFrame(ev_rows)
    excess = pd.concat(ex_rows, ignore_index=True) if ex_rows else pd.DataFrame(columns=["date", "entity", "excess"])
    meta = dict(family=family, seed=seed, n_days=n_days, n_entities=n_ent, start_date=start_date)
    return SynthDataset(family, seed, panel, events, excess, meta)


def save(ds: SynthDataset, outdir: str | Path) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    ds.panel.to_csv(out / "panel.csv", index=False)
    ds.events.to_csv(out / "events.csv", index=False)
    ds.excess[ds.excess["excess"] > 0].to_csv(out / "excess.csv", index=False)
    return out
