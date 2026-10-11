"""Small statistics helpers: Wilson intervals for proportions, t intervals for means, paired differences."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as st


def wilson(k: float, n: float, conf: float = 0.95) -> tuple[float, float, float]:
    if n <= 0:
        return (float("nan"),) * 3
    z = st.norm.ppf(0.5 + conf / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def mean_ci(x, conf: float = 0.95) -> tuple[float, float, float]:
    a = np.asarray([v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))], dtype=float)
    if len(a) == 0:
        return (float("nan"),) * 3
    m = float(a.mean())
    if len(a) < 2:
        return m, float("nan"), float("nan")
    h = float(st.t.ppf(0.5 + conf / 2, len(a) - 1) * a.std(ddof=1) / math.sqrt(len(a)))
    return m, m - h, m + h


def fmt_ci(m: float, lo: float, hi: float, d: int = 2, pct: bool = False) -> str:
    if math.isnan(m):
        return "n/a"
    k = 100.0 if pct else 1.0
    s = "%" if pct else ""
    if math.isnan(lo):
        return f"{m * k:.{d}f}{s}"
    return f"{m * k:.{d}f}{s} [{lo * k:.{d}f}, {hi * k:.{d}f}]"
