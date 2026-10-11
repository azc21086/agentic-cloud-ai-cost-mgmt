"""Client for any OpenAI-compatible chat endpoint (OpenAI, Azure OpenAI gateways, vLLM, Ollama, OpenRouter, ...).

The key is read from the argument or the environment (GCSI_API_KEY, then OPENAI_API_KEY). It is never logged or cached.
"""
from __future__ import annotations

import os
import time

from .base import LLMResponse


class OpenAICompatClient:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        json_mode: bool = True,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise ImportError("install the optional dependency: pip install 'gcsi-governance[llm]'") from e
        key = api_key or os.environ.get("GCSI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("no API key: set GCSI_API_KEY or OPENAI_API_KEY, or pass api_key")
        self.model = model
        self.name = model
        self.json_mode = json_mode
        self.max_retries = max_retries
        self._client = OpenAI(api_key=key, base_url=base_url or os.environ.get("GCSI_BASE_URL") or None, timeout=timeout)

    def complete(self, system, user, *, temperature=0.0, seed=None, repeat=0) -> LLMResponse:
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )
        if seed is not None:
            kwargs["seed"] = seed + repeat
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        last_err = None
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                r = self._client.chat.completions.create(**kwargs)
                u = getattr(r, "usage", None)
                return LLMResponse(
                    text=r.choices[0].message.content or "",
                    model=getattr(r, "model", self.model),
                    latency_s=time.time() - t0,
                    prompt_tokens=getattr(u, "prompt_tokens", None),
                    completion_tokens=getattr(u, "completion_tokens", None),
                )
            except Exception as e:  # network, rate limit, unsupported parameter
                last_err = f"{type(e).__name__}: {e}"
                if "response_format" in str(e) and "response_format" in kwargs:
                    kwargs.pop("response_format")  # endpoint without JSON mode; fall back to prompt-only control
                    continue
                time.sleep(min(2**attempt, 8))
        return LLMResponse(text="", model=self.model, error=last_err)
