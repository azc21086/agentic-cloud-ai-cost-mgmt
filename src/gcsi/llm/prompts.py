"""Prompt templates for the reasoning layer (version-controlled; the hash is stored in every decision trail)."""
from __future__ import annotations

import json

from ..schema import ACTION_CATALOG, INPUT_REFS
from .base import prompt_hash

PROMPT_VERSION = "decision_record_v1"

SYSTEM_PROMPT = f"""You are the reasoning layer of a cloud financial governance system.
You receive one evidence packet describing a deviation between actual and forecast cloud spend.
You do not execute anything. You return one decision record as a single JSON object and nothing else.

Required JSON fields:
- "event": short string describing the deviation (entity, dates, size).
- "causal_factors": list of objects {{"factor": str, "evidence_ref": one of {list(INPUT_REFS)}, "share": number 0 to 1}}.
  Every factor must cite an input that supports it. Shares must sum to 1.
- "financial_impact": {{"value_usd_per_week": number, "low": number, "high": number}}. Derive it from the evidence,
  do not invent figures. It is the size of the deviation per week, whatever its cause.
- "recommended_action": {{"class": one of {list(ACTION_CATALOG)}, "params": object}}. Choose only from this catalog.
- "confidence": number from 0 to 1 for your confidence that the diagnosis and action are right.
- "rationale": one or two sentences.

Guidance: if usage rose in line with spend (usage_explained_share close to 1) the deviation is probably demand-driven and
the baseline should be recalculated. If spend rose while usage did not, treat it as possible waste and choose the
action class that fits the shape (step: stop_idle_resource; ramp: apply_budget_cap; brief spike: send_alert).
If the evidence is insufficient, choose send_alert with low confidence. Do not use the words or fields of any other schema."""

EVIDENCE_OPEN, EVIDENCE_CLOSE = "<<<EVIDENCE", "EVIDENCE>>>"


def build_user_prompt(evidence: dict) -> str:
    return f"{EVIDENCE_OPEN}\n{json.dumps(evidence, sort_keys=True)}\n{EVIDENCE_CLOSE}"


def prompt_ref(system: str = SYSTEM_PROMPT) -> str:
    return f"{PROMPT_VERSION}:{prompt_hash(system, '')}"
