"""Configuration objects. All thresholds are policy parameters, not calibrated values."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


def _digest(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


@dataclass(frozen=True)
class PolicyConfig:
    """Governance policy theta = (A0, tau_I, tau_c) plus validation tolerances (paper Section 3.1)."""

    tau_impact_usd: float = 5000.0  # materiality threshold, USD per week
    tau_conf: float = 0.80  # minimum confidence for autonomous handling
    auto_actions: tuple = ("no_action", "recalculate_baseline", "send_alert")  # A0
    period_days: int = 7  # impact is expressed per week
    impact_ratio_tolerance: float = 2.0  # business rule: stated impact within a factor of the measured one
    consistency_tolerance: float = 0.30  # repeat runs may differ by at most 30% in impact
    unsupported_factor_penalty: float = 0.15  # confidence multiplier loss per unsupported causal factor
    share_sum_tolerance: float = 0.15  # causal-factor shares must sum to 1 within this tolerance

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class ResidualConfig:
    """Usage-aware forecast-residual detector."""

    min_train_days: int = 28
    window_days: int = 42
    refit_every: int = 7
    z_thresh: float = 3.5
    spike_z: float = 1e9  # a single day at or above this z is confirmed immediately (disabled by default)
    persistence: int = 2  # consecutive flagged days needed for confirmation
    min_abs_excess_usd: float = 25.0
    min_rel_excess: float = 0.10
    scale_floor_abs: float = 10.0
    scale_floor_rel: float = 0.03
    use_usage: bool = True


@dataclass(frozen=True)
class ThresholdConfig:
    """Fixed-threshold alert: spend above trailing mean by pct and by a minimum dollar amount."""

    window_days: int = 14
    pct: float = 0.30
    min_abs_excess_usd: float = 25.0


@dataclass(frozen=True)
class EconomicsConfig:
    """Assumed operating parameters for the decision-economics simulation (not measurements)."""

    human_triage_days: float = 3.0  # time from alert to resolution when a human investigates from scratch
    review_days: float = 1.0  # time from a prepared decision record to a human decision
    kappa_review_usd: float = 50.0  # cost of one human review or triage
    kappa_alert_usd: float = 5.0  # cost of one automated alert
    disruption_cost_usd: float = 2000.0  # cost of executing an unnecessary or misdirected action
    reviewer_accuracy: float = 1.0  # probability a human reviewer reaches the right decision


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "mock"  # mock | openai (any OpenAI-compatible endpoint)
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    temperature: float = 0.0
    seed: int | None = None
    repeats: int = 1  # evaluations per incident, used by the consistency control
    max_calls: int | None = None
    cache_path: str | None = None
    mock_fault_rate: float = 0.15  # mock only: share of responses corrupted on purpose


@dataclass(frozen=True)
class ExperimentConfig:
    families: tuple = ("steady", "volatile", "growth", "lumpy")
    n_seeds: int = 20
    base_seed: int = 1000
    n_days: int = 120
    n_waste_events: int = 6
    n_benign_events: int = 3
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    residual: ResidualConfig = field(default_factory=ResidualConfig)
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)
    economics: EconomicsConfig = field(default_factory=EconomicsConfig)
    llm: LLMSettings = field(default_factory=LLMSettings)

    def digest(self) -> str:
        return _digest(asdict(self))
