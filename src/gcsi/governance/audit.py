"""Append-only audit log (control v). One JSON object per line."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trail_entry(actor: str, decision: str, rationale: str = "", ts: str | None = None) -> dict:
    return {"actor": actor, "decision": decision, "rationale": rationale, "timestamp": ts or now_iso()}


class AuditLog:
    def __init__(self, path: str | Path | None = None, keep_in_memory: bool = True):
        self.path = Path(path) if path else None
        self.keep = keep_in_memory
        self.events: list[dict] = []
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, payload: dict) -> None:
        rec = {"ts": now_iso(), "kind": kind, **payload}
        with self._lock:
            if self.keep:
                self.events.append(rec)
            if self.path:
                with open(self.path, "a") as fh:
                    fh.write(json.dumps(rec, default=str) + "\n")
