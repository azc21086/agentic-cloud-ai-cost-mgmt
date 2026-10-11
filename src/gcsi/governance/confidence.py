"""Confidence score used by the router (paper Section 3.1, control ii).

Final confidence c = min(c_model_adjusted, c_stat), where
  c_model_adjusted = model-stated confidence * (1 - penalty)^(number of unsupported causal factors)
  c_stat           = confidence implied by the measured evidence and by agreement between the chosen action and the data.

The model's own number is therefore never enough to reach AUTO: the evidence must support it as well.
The functional forms and constants are illustrative design choices, not calibrated values.
"""
from __future__ import annotations

import math

from ..config import PolicyConfig
from ..schema import EXPLAINED_ACTIONS


def signal_confidence(z: float, persistence_days: int) -> float:
    """How surely the deviation is real: logistic in the residual z-score, scaled by persistence."""
    s = 1.0 / (1.0 + math.exp(-(z - 4.0) / 1.2))
    p = min(1.0, 0.5 + 0.25 * persistence_days)
    return s * p


def statistical_confidence(action: str, evidence: dict) -> float:
    share = evidence.get("usage_explained_share")
    share = 0.0 if share is None else float(share)
    if action in EXPLAINED_ACTIONS:
        # Treating the deviation as explained is only supported to the extent that usage explains it.
        return max(0.0, min(1.0, share))
    sig = signal_confidence(float(evidence.get("z_score") or 0.0), int(evidence.get("persistence_days") or 1))
    # Treating it as waste is weakened when usage explains the rise.
    return sig * (1.0 - share)


def combine(c_model: float, n_unsupported: int, action: str, evidence: dict, policy: PolicyConfig) -> dict:
    adj = c_model * (1.0 - policy.unsupported_factor_penalty) ** n_unsupported
    c_stat = statistical_confidence(action, evidence)
    final = max(0.0, min(1.0, min(adj, c_stat)))
    return {
        "model_stated": round(c_model, 4),
        "model_adjusted": round(adj, 4),
        "statistical": round(c_stat, 4),
        "unsupported_factors": n_unsupported,
        "final": round(final, 4),
    }
