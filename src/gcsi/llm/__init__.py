from .base import CachedLLM, LLMClient, LLMResponse, prompt_hash
from .mock import MockLLM
from .openai_compat import OpenAICompatClient
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt, prompt_ref


def make_client(settings, api_key: str | None = None):
    """Build a client from LLMSettings. 'mock' needs no key; 'openai' means any OpenAI-compatible endpoint."""
    if settings.provider == "mock":
        inner = MockLLM(fault_rate=settings.mock_fault_rate, seed=settings.seed or 0)
    elif settings.provider == "openai":
        inner = OpenAICompatClient(model=settings.model, api_key=api_key, base_url=settings.base_url)
    else:
        raise ValueError(f"unknown provider {settings.provider}")
    return CachedLLM(inner, path=settings.cache_path, max_calls=settings.max_calls)


__all__ = [
    "CachedLLM", "LLMClient", "LLMResponse", "MockLLM", "OpenAICompatClient", "PROMPT_VERSION", "SYSTEM_PROMPT",
    "build_user_prompt", "prompt_ref", "prompt_hash", "make_client",
]
