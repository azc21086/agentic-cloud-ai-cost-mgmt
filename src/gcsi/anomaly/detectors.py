"""Anomaly detectors. Both return one row per entity-day with the same columns.

Output columns: date, entity, spend, usage, expected, scale, z, excess, flag, alert
  flag  : the day breaches the detector's rule
  alert : the day on which an alert is confirmed (persistence rule satisfied)
Only data up to and including a day is used to score that day (no look-ahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ResidualConfig, ThresholdConfig
from ..forecast import design_matrix, fit_ols
from ..ingest import densify

OUT_COLUMNS = ["date", "entity", "spend", "usage", "expected", "scale", "z", "excess", "flag", "alert"]


def _frame(g: pd.DataFrame, expected, scale, z, flag, alert) -> pd.DataFrame:
    spend = g["spend"].to_numpy(float)
    return pd.DataFrame(
        {
            "date": g["date"].to_numpy(),
            "entity": g["entity"].to_numpy(),
            "spend": spend,
            "usage": g["usage"].to_numpy(float),
            "expected": expected,
            "scale": scale,
            "z": z,
            "excess": spend - expected,
            "flag": flag,
            "alert": alert,
        }
    )[OUT_COLUMNS]


def _confirm(flag: np.ndarray, z: np.ndarray, persistence: int, spike_z: float) -> np.ndarray:
    """Alert on the day a flag streak reaches `persistence` days, or at once for an extreme single-day z."""
    alert = np.zeros(len(flag), dtype=bool)
    streak = 0
    for i, f in enumerate(flag):
        streak = streak + 1 if f else 0
        if f and (streak >= persistence or z[i] >= spike_z):
            alert[i] = True
    return alert


def residual_detector(panel: pd.DataFrame, cfg: ResidualConfig = ResidualConfig()) -> pd.DataFrame:
    """Usage-aware forecast-residual detector.

    For each entity the spend model is refitted every `refit_every` days on the trailing window. Flagged days are
    excluded from later fits and the model is frozen while a flag streak is open, so a persistent anomaly cannot be
    absorbed into the baseline. Residuals are scaled by a robust (MAD) estimate.
    """
    panel = densify(panel)
    parts = []
    for _, g in panel.groupby("entity", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        y = g["spend"].to_numpy(float)
        u = g["usage"].to_numpy(float)
        X = design_matrix(g["date"].to_numpy(), u, g["date"].iloc[0], use_usage=cfg.use_usage)
        expected = np.full(n, np.nan)
        scale = np.full(n, np.nan)
        z = np.full(n, np.nan)
        flag = np.zeros(n, dtype=bool)
        excluded = np.zeros(n, dtype=bool)
        beta, sc, fit_t, streak = None, None, -(10**9), 0
        for t in range(cfg.min_train_days, n):
            if (beta is None or t - fit_t >= cfg.refit_every) and streak == 0:
                lo = max(0, t - cfg.window_days)
                idx = np.arange(lo, t)[~excluded[lo:t]]
                if len(idx) >= int(0.6 * cfg.min_train_days):
                    f = fit_ols(X[idx], y[idx], cfg.scale_floor_abs, cfg.scale_floor_rel)
                    beta, sc, fit_t = f.beta, f.scale, t
            if beta is None:
                continue
            expected[t] = max(float(X[t] @ beta), 0.0)
            scale[t] = sc
            r = y[t] - expected[t]
            z[t] = r / sc
            is_flag = z[t] >= cfg.z_thresh and r >= max(cfg.min_abs_excess_usd, cfg.min_rel_excess * expected[t])
            flag[t] = is_flag
            streak = streak + 1 if is_flag else 0
            if is_flag:
                excluded[t] = True
        alert = _confirm(flag, np.nan_to_num(z, nan=0.0), cfg.persistence, cfg.spike_z)
        parts.append(_frame(g, expected, scale, z, flag, alert))
    return pd.concat(parts, ignore_index=True)


def threshold_detector(panel: pd.DataFrame, cfg: ThresholdConfig = ThresholdConfig()) -> pd.DataFrame:
    """Fixed-threshold alert: spend exceeds the trailing mean by `pct` and by at least `min_abs_excess_usd`.

    This is the conventional budget or percent-change alert. It has no usage context and no persistence rule.
    """
    panel = densify(panel)
    parts = []
    for _, g in panel.groupby("entity", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        s = g["spend"]
        base = s.shift(1).rolling(cfg.window_days, min_periods=cfg.window_days).mean().to_numpy()
        y = s.to_numpy(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            flag = (y > base * (1 + cfg.pct)) & ((y - base) >= cfg.min_abs_excess_usd)
        flag = np.where(np.isnan(base), False, flag)
        scale = np.maximum(base * cfg.pct, 1e-9)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = (y - base) / scale
        parts.append(_frame(g, base, scale, z, flag, flag.copy()))
    return pd.concat(parts, ignore_index=True)


DETECTORS = {"residual": residual_detector, "threshold": threshold_detector}
