"""Admin · the platform's LLM provider keys: app-scope secrets, kept in Imperal Vault.

One key per provider. Declared here with the SDK, typed by an admin in this
extension's Secrets manager (/ext/admin/secrets), stored by the gateway's
secret store behind Imperal Vault. The names are a contract with auth-gateway
app/unified_config/llm_keys.py, which gives the keys to the kernel:

    llm_<provider>_api_key        e.g. llm_openrouter_api_key

No key is in the LLM config, in Redis or in the environment, and no field of
the LLM Config page accepts one (owner, 2026-11-23: "Все ключи строго из него
должны доставаться, никакого редиса"). This extension reads a key only for a
model listing or a Test button, through ctx.secrets.
"""
from __future__ import annotations

import asyncio
import logging

from app import ext

log = logging.getLogger("admin")

SECRET_OWNER = "admin"

# provider id -> label; the ids are the ones the LLM config stores
PROVIDERS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "openrouter": "OpenRouter",
    "qwen": "Qwen",
    "kimi": "Kimi",
    "zhipu": "Zhipu",
    "openai_compatible": "Custom (OpenAI-compatible)",
}


def provider_id(provider) -> str:
    p = str(provider or "").strip().lower()
    return "openai_compatible" if p == "custom" else p


def secret_name(provider) -> str:
    return f"llm_{provider_id(provider)}_api_key"


LLM_KEY_SECRETS: dict[str, str] = {
    secret_name(_p): f"API key of {_label} for the platform's LLM calls. "
                     "Every model of this provider, in any task, uses it."
    for _p, _label in PROVIDERS.items()
}
for _name, _description in LLM_KEY_SECRETS.items():
    ext.secret(name=_name, description=_description, scope="app", max_bytes=400)(lambda: None)


def secrets_path(provider) -> str:
    return f"/ext/{SECRET_OWNER}/secrets#{secret_name(provider)}"


async def key_for(ctx, provider) -> str:
    """The provider's key from the secret store, or "" when none is typed.
    Raises when the store cannot be read: the caller says so, it does not guess."""
    p = provider_id(provider)
    secrets = getattr(ctx, "secrets", None)
    if p not in PROVIDERS or secrets is None:
        return ""
    return await secrets.get(secret_name(p)) or ""


async def keys_set(ctx) -> dict[str, bool] | None:
    """provider -> whether its key is typed; None when the store could not be asked."""
    secrets = getattr(ctx, "secrets", None)
    if secrets is None:
        return None
    try:
        # side by side: eight reads one after another were eight round trips in a row
        answers = await asyncio.gather(*[secrets.is_set(secret_name(p)) for p in PROVIDERS])
    except Exception as e:
        log.warning("llm keys: the secret store did not answer: %s: %s", type(e).__name__, e)
        return None
    return {p: bool(a) for p, a in zip(PROVIDERS, answers)}
