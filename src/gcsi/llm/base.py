"""Provider-agnostic LLM interface plus a disk cache that makes runs replayable without a key."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    model: str
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    cached: bool = False
    meta: dict | None = None  # provider-specific notes, e.g. the fault injected by the mock


class LLMClient(Protocol):
    """Any object with a `name` and a `complete` method can serve as the reasoning layer."""

    name: str

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, seed: int | None = None, repeat: int = 0
    ) -> LLMResponse: ...


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16]


@dataclass
class CachedLLM:
    """Wraps a client. Responses are keyed by (model, prompt, temperature, seed, repeat) and appended to a JSONL file.

    A cache hit costs nothing and returns the identical text, so an experiment can be re-scored offline from the
    cache file alone. `max_calls` bounds the number of live (uncached) calls.
    """

    inner: LLMClient
    path: str | None = None
    max_calls: int | None = None
    live_calls: int = 0
    hits: int = 0
    _mem: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.name = getattr(self.inner, "name", "llm")
        if self.path and Path(self.path).exists():
            with open(self.path) as fh:
                for line in fh:
                    if line.strip():
                        r = json.loads(line)
                        self._mem[r["key"]] = r

    @staticmethod
    def key(model: str, system: str, user: str, temperature: float, seed, repeat: int) -> str:
        return hashlib.sha256(json.dumps([model, system, user, temperature, seed, repeat]).encode()).hexdigest()

    def complete(self, system, user, *, temperature=0.0, seed=None, repeat=0) -> LLMResponse:
        k = self.key(self.name, system, user, temperature, seed, repeat)
        with self._lock:
            if k in self._mem:
                r = self._mem[k]
                self.hits += 1
                return LLMResponse(
                    text=r["text"], model=r["model"], latency_s=r.get("latency_s", 0.0),
                    prompt_tokens=r.get("prompt_tokens"), completion_tokens=r.get("completion_tokens"),
                    error=r.get("error"), cached=True, meta=r.get("meta"),
                )
            if self.max_calls is not None and self.live_calls >= self.max_calls:
                raise RuntimeError(f"max_calls={self.max_calls} reached; rerun with the same cache to continue")
            self.live_calls += 1
        resp = self.inner.complete(system, user, temperature=temperature, seed=seed, repeat=repeat)
        rec = {
            "key": k, "model": resp.model, "prompt_ref": prompt_hash(system, user), "repeat": repeat,
            "temperature": temperature, "seed": seed, "text": resp.text, "latency_s": resp.latency_s,
            "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens, "error": resp.error,
            "meta": resp.meta,
        }
        with self._lock:
            self._mem[k] = rec
            if self.path:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
        return resp
