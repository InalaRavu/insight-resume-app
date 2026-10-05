"""LLM provider chain with automatic failover.

HuggingFace's router is the primary provider but its free tier is rate limited,
so each configured provider is tried in order until one returns a completion.
Every provider here speaks the OpenAI chat-completions dialect, which keeps the
call site identical regardless of who actually serves the request.
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import httpx
from openai import OpenAI

from src import config  # noqa: F401 - ensures .env is loaded before the constants below

log = logging.getLogger("nexa.llm")

# Disabling TLS verification is only tolerable behind a corporate MITM proxy and
# must be an explicit, deliberate opt-in -- resumes are PII.
VERIFY_TLS = os.getenv("LLM_VERIFY_TLS", "true").lower() not in ("false", "0", "no")
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))


class AllProvidersFailed(RuntimeError):
    """Raised when every configured provider has been exhausted."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


def _provider(name: str, key_env: str, base_url: str, model_env: str, default_model: str) -> Optional[Provider]:
    api_key = os.getenv(key_env)
    if not api_key:
        return None
    return Provider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=os.getenv(model_env, default_model),
    )


def build_chain() -> List[Provider]:
    """Providers in failover order; unconfigured ones are skipped silently."""
    candidates = [
        _provider(
            "huggingface",
            "HF_API_KEY",
            "https://router.huggingface.co/v1",
            "HF_MODEL",
            "Qwen/Qwen2.5-72B-Instruct",
        ),
        _provider(
            "groq",
            "GROQ_API_KEY",
            "https://api.groq.com/openai/v1",
            "GROQ_MODEL",
            "llama-3.3-70b-versatile",
        ),
        _provider(
            "gemini",
            "GEMINI_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        ),
        _provider(
            "cerebras",
            "CEREBRAS_API_KEY",
            "https://api.cerebras.ai/v1",
            "CEREBRAS_MODEL",
            "llama-3.3-70b",
        ),
    ]

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if azure_endpoint and azure_key and azure_deployment:
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        candidates.append(
            Provider(
                name="azure-openai",
                base_url=f"{azure_endpoint.rstrip('/')}/openai/deployments/{azure_deployment}"
                         f"?api-version={api_version}",
                api_key=azure_key,
                model=azure_deployment,
            )
        )

    chain = [p for p in candidates if p is not None]

    # Honour an explicit priority list, e.g. LLM_PROVIDER_ORDER="gemini,huggingface"
    order = os.getenv("LLM_PROVIDER_ORDER")
    if order:
        wanted = [n.strip().lower() for n in order.split(",") if n.strip()]
        by_name = {p.name: p for p in chain}
        chain = [by_name[n] for n in wanted if n in by_name]

    return chain


_http_client = httpx.Client(verify=VERIFY_TLS, trust_env=True, timeout=REQUEST_TIMEOUT)


def _client_for(provider: Provider) -> OpenAI:
    # max_retries=0 is deliberate. The SDK retries internally by default, which
    # multiplies with the attempt loop below (2 x 3 = 6 slow calls to a
    # rate-limited provider) and delays failover past the UI's timeout. Retries
    # are owned here, where they can fall through to the next provider.
    kwargs = {
        "base_url": provider.base_url,
        "api_key": provider.api_key,
        "http_client": _http_client,
        "max_retries": 0,
    }
    if provider.name == "azure-openai":
        kwargs["default_query"] = {}
        kwargs["default_headers"] = {"api-key": provider.api_key}
    return OpenAI(**kwargs)


def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
    temperature: float = 0.1,
    attempts_per_provider: int = 2,
) -> str:
    """Return the assistant message text from the first provider that succeeds."""
    chain = build_chain()
    if not chain:
        raise AllProvidersFailed(
            "No LLM provider configured. Set at least one of HF_API_KEY, GROQ_API_KEY, "
            "GEMINI_API_KEY, CEREBRAS_API_KEY, or the AZURE_OPENAI_* trio in your .env."
        )

    errors = []
    for provider in chain:
        for attempt in range(1, attempts_per_provider + 1):
            try:
                completion = _client_for(provider).chat.completions.create(
                    model=provider.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = (completion.choices[0].message.content or "").strip()
                if not content:
                    raise ValueError("provider returned an empty message")
                log.info("LLM completion served by %s (%s)", provider.name, provider.model)
                return content
            except Exception as exc:  # noqa: BLE001 - any failure should fail over
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                log.warning("Provider %s attempt %d/%d failed: %s",
                            provider.name, attempt, attempts_per_provider, exc)
                if attempt < attempts_per_provider:
                    time.sleep(1.5 * attempt)  # brief backoff before retrying the same provider

    raise AllProvidersFailed("All LLM providers failed.\n" + "\n".join(errors))


def chain_status() -> List[dict]:
    """Provider inventory for the /health endpoint (never exposes key material)."""
    return [{"name": p.name, "model": p.model} for p in build_chain()]
