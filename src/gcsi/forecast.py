"""Time-aware, usage-driven spend forecasting with prediction intervals.

Model: spend_t = b0 + b1 * trend_t + b2 * usage_t + weekday effects + e_t, fitted by least squares on a trailing
window. Intervals use a robust residual scale (1.4826 * MAD). The split is always chronological: the model never sees
data after the day it predicts. A seasonal-naive and a trailing-mean baseline are reported alongside for context.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600}


def design_matrix(dates: np.ndarray, usage: np.ndarray | None, origin, use_usage: bool = True) -> np.ndarray:
    """Columns: intercept, trend (days from origin / 30), usage (optional), six weekday dummies."""
    d = pd.DatetimeIndex(dates)
    n = len(d)
    t = ((d - pd.Timestamp(origin)).days.to_numpy(dtype=float)) / 30.0
    cols = [np.ones(n), t]
    if use_usage and usage is not None and not np.all(np.isnan(usage)):
        u = np.asarray(usage, dtype=float)
        fill = np.nanmean(u) if not np.all(np.isnan(u)) else 0.0
        cols.append(np.where(np.isnan(u), fill, u))
    dow = d.dayofweek.to_numpy()
    for k in range(1, 7):
        cols.append((dow == k).astype(float))
    return np.column_stack(cols)


@dataclass
class Fit:
    beta: np.ndarray
    scale: float
    n_train: int


def fit_ols(
    X: np.ndarray, y: np.ndarray, scale_floor_abs: float = 10.0, scale_floor_rel: float = 0.03
) -> Fit:
    """Least squares with column scaling for conditioning and a robust residual scale."""
    s = np.where(X.std(axis=0) > 1e-12, X.std(axis=0), 1.0)
    s[0] = 1.0
    bs, *_ = np.linalg.lstsq(X / s, y, rcond=None)
    beta = bs / s
    resid = y - X @ beta
    n, p = X.shape
    mad = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    infl = np.sqrt(n / max(n - p, 1))
    floor = max(scale_floor_abs, scale_floor_rel * float(np.mean(np.abs(y))))
    return Fit(beta=beta, scale=float(max(mad * infl, floor)), n_train=n)


def trim_leading_zeros(df: pd.DataFrame, col: str = "spend") -> pd.DataFrame:
    nz = np.flatnonzero(df[col].to_numpy() > 0)
    return df.iloc[nz[0] :].reset_index(drop=True) if len(nz) else df.iloc[0:0]


def _wape(y, yhat) -> float:
    d = np.sum(np.abs(y))
    return float(np.sum(np.abs(y - yhat)) / d) if d > 0 else float("nan")


def rolling_origin_backtest(
    series: pd.DataFrame, initial: int = 28, horizon: int = 7, step: int = 7, window: int = 42, level: float = 0.80
) -> dict:
    """Chronological backtest on one series with columns date, spend, usage.

    At each origin the model is fitted on the trailing window and predicts the next `horizon` days, using the
    actual usage for those days (an oracle-usage backtest, which isolates the spend model from usage forecasting).
    Returns WAPE for the model, a seasonal-naive baseline (same weekday last week) and a 14-day trailing mean.
    """
    s = series.reset_index(drop=True)
    y_all = s["spend"].to_numpy(float)
    dates = s["date"].to_numpy()
    u_all = s["usage"].to_numpy(float) if "usage" in s else None
    origin = dates[0]
    X_all = design_matrix(dates, u_all, origin)
    ys, ym, yn, yt, cover = [], [], [], [], []
    z = Z[level]
    t = initial
    while t + horizon <= len(s):
        lo = max(0, t - window)
        fit = fit_ols(X_all[lo:t], y_all[lo:t])
        pred = X_all[t : t + horizon] @ fit.beta
        act = y_all[t : t + horizon]
        ys.append(act)
        ym.append(pred)
        yn.append(y_all[t - 7 : t - 7 + horizon] if t - 7 >= 0 else np.full(horizon, np.nan))
        yt.append(np.full(horizon, y_all[max(0, t - 14) : t].mean()))
        cover.append((act >= pred - z * fit.scale) & (act <= pred + z * fit.scale))
        t += step
    if not ys:
        return {"n_origins": 0}
    y, ym, yn, yt = map(np.concatenate, (ys, ym, yn, yt))
    ok = ~np.isnan(yn)
    return {
        "n_origins": len(ys),
        "n_points": int(len(y)),
        "wape_model": _wape(y, ym),
        "wape_seasonal_naive": _wape(y[ok], yn[ok]),
        "wape_trailing_mean": _wape(y, yt),
        "interval_level": level,
        "interval_coverage": float(np.concatenate(cover).mean()),
    }


def _project_usage(usage: np.ndarray, horizon: int, lookback: int = 28) -> np.ndarray:
    u = usage[-lookback:]
    u = u[~np.isnan(u)]
    if len(u) < 3:
        return np.full(horizon, float(np.nanmean(usage)) if len(u) else 0.0)
    x = np.arange(len(u))
    b1, b0 = np.polyfit(x, u, 1)
    fut = b0 + b1 * np.arange(len(u), len(u) + horizon)
    return np.clip(fut, 0.0, None)


def forecast_future(series: pd.DataFrame, horizon: int = 30, window: int = 42, level: float = 0.80) -> pd.DataFrame:
    """Point forecast and interval for the next `horizon` days. Future usage is a linear projection of recent usage."""
    s = series.reset_index(drop=True)
    dates = pd.DatetimeIndex(s["date"])
    y = s["spend"].to_numpy(float)
    u = s["usage"].to_numpy(float) if "usage" in s else None
    X = design_matrix(dates.to_numpy(), u, dates[0])
    lo = max(0, len(s) - window)
    fit = fit_ols(X[lo:], y[lo:])
    fdates = pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    fu = _project_usage(u, horizon) if u is not None and not np.all(np.isnan(u)) else None
    Xf = design_matrix(fdates.to_numpy(), fu, dates[0], use_usage=u is not None and not np.all(np.isnan(u)))
    yhat = np.clip(Xf @ fit.beta, 0.0, None)
    z = Z[level]
    return pd.DataFrame(
        {"date": fdates, "yhat": yhat, "lo": np.clip(yhat - z * fit.scale, 0.0, None), "hi": yhat + z * fit.scale}
    )


def product_series(panel: pd.DataFrame, product: str) -> pd.DataFrame:
    """Daily spend and usage for one product, summed over its entities."""
    p = panel[panel["product"] == product]
    g = p.groupby("date").agg(spend=("spend", "sum"), usage=("usage", "mean")).reset_index()
    return g


def backtest_table(panel: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = []
    for prod in sorted(panel["product"].unique()):
        s = trim_leading_zeros(product_series(panel, prod))
        r = rolling_origin_backtest(s, **kw) if len(s) >= 35 else {"n_origins": 0}
        rows.append({"product": prod, "days_used": len(s), **r})
    return pd.DataFrame(rows)
