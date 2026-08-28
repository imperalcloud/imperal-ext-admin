"""Admin · LLM routing model — WHICH model actually runs, and what it costs.

The panel could always SET a model, but nothing could answer the operator's
real question: *for this purpose, which model will actually run, at which
tier, and what does one action therefore cost?*

That gap is not cosmetic. Charging is per action, but the per-action platform
fee is per TIER, and the tier is a property of the model that ends up running
-- so an identical 5-action automation costs ~305 credits on `economy` and
~11,005 on `premium`. With the effective model invisible, that 37x swing looks
like random billing.

This module is deliberately pure: no HTTP, no ctx, no side effects. It encodes
the same cascade the kernel resolves and is unit-testable on its own, so the
answers the admin tools give are reproducible rather than narrated.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# ── The purposes an operator can actually be billed for ─────────────────── #
#
# Mirrors _PURPOSE_MODELS in panels_llm_form.py (the form the admin fills in)
# plus the three Webbee Code tiers. Kept as data, not scattered literals, so a
# new purpose shows up in diagnostics automatically instead of silently
# becoming a blind spot -- which is exactly how `resolve` stayed invisible.
PURPOSE_SLOTS: tuple[tuple[str, str], ...] = (
    ("resolve",         "Universal Brain · Reasoning (chat + EVERY automation run)"),
    ("code",            "Coding Brain · Webbee Code terminal turns"),
    ("routing",         "Routing · intent classifier, runs on every user turn"),
    ("execution",       "Execution · tool dispatch and automation actions"),
    ("navigate",        "Navigate · clarifying questions and offers"),
    ("chain_narrative", "Chain Narrator · final multi-step reply"),
    ("judge",           "Judge · anti-fabrication gate"),
    ("conversational",  "Conversational · chitchat fall-through"),
    ("step_reclassify", "Step Reclassify · binds args before write steps"),
    ("tool_picker",     "Tool Picker · chain disambiguation"),
    ("action_narrator", "Action Narrator · post-tool prose"),
)

# Webbee Code quality tiers. The key MUST match MODEL_TIERS in the kernel's
# llm/model_tiers.py verbatim: this form once shipped writing "smart_model",
# a key nothing read, so the Webbee Smart row was inert while the tier quietly
# resolved through a different cascade. Same class of bug as `resolve`.
CODE_TIER_SLOTS: tuple[tuple[str, str], ...] = (
    ("webbeesmart", "Webbee Smart · default everyday tier"),
    ("supersmart",  "Webbee SuperSmart · harder tasks"),
    ("ultrasmart",  "Webbee UltraSmart · hardest tasks"),
)

# Slots that can substitute a DIFFERENT model than the one the admin picked,
# without any further human choice. These are the ones that turn a stable
# config into a variable bill, so diagnostics must always report them.
SUBSTITUTION_SLOTS: tuple[tuple[str, str], ...] = (
    ("failover",        "Failover · silently retries on another model when the provider errors"),
    ("override",        "Per-extension override · forces a model for one extension"),
)

# Defaults mirrored from panels_system_pricing.py (_DEFAULT_FEES/_DEFAULT_CATS).
# Used ONLY when the live billing config cannot be read, and every response
# says which of the two it used -- a fee silently guessed is a fee that
# misleads an operator about real money.
DEFAULT_TIER_FEES: dict[str, int] = {"economy": 60, "standard": 250, "premium": 2200}
DEFAULT_CATEGORY_PRICES: dict[str, int] = {"read": 1, "write": 5, "destructive": 10}

# The tier assumed for a model that has NO rate row at all. Deliberately the
# cheapest: an unpriced model must never be able to bill as `premium` by
# accident. Diagnostics still flag it loudly as unpriced.
UNKNOWN_TIER = "unpriced"

# Provider inference by model-id prefix. Mirrors _PROVIDER_PREFIXES in
# panels_llm_models.py deliberately rather than importing it: that module
# pulls in redis + httpx for live catalogue fetches, and this one must stay
# pure so the routing answers are unit-testable without a network.
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("qwen", "qwen"),
    ("qwq", "qwen"),
    # DashScope-hosted families (same key, same endpoint) — see
    # panels_llm_models._QWEN_HOSTED_PREFIXES.
    ("deepseek", "qwen"),
    ("glm", "qwen"),
    ("kimi", "qwen"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("chatgpt", "openai"),
    ("gemini", "google"),
)


def _provider_for_model(model: str) -> str:
    """Infer the provider from a model id by prefix. '' if unknown."""
    m = (model or "").lower()
    for prefix, prov in _PROVIDER_PREFIXES:
        if m.startswith(prefix):
            return prov
    return ""


class ModelRate(BaseModel):
    """One row of the LLM model rate table (`/v1/internal/billing/model-rates`)."""
    model_id: str = ""
    tier: str = ""
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    is_available: bool = True


class ResolvedSlot(BaseModel):
    """What a single purpose slot resolves to, and why.

    `source` is the point of the whole record: an operator seeing an
    unexpected tier needs to know whether the model came from their own
    explicit choice, from the global default, or from a substitution slot
    they never picked.
    """
    purpose: str = ""
    label: str = ""
    configured_model: str = Field(default="", description="What the slot itself holds ('' = inherits)")
    effective_model: str = Field(default="", description="The model that will ACTUALLY run")
    provider: str = ""
    source: str = Field(default="", description="explicit | inherited_default | unset")
    tier: str = Field(default="", description="Billing tier of the effective model")
    platform_fee: int = Field(default=0, description="Credits charged per action at this tier")
    is_available: bool = True
    is_priced: bool = Field(default=True, description="False = model has no rate row")
    warnings: list[str] = Field(default_factory=list)


def normalise_rates(raw: list[dict] | None) -> dict[str, ModelRate]:
    """Index rate rows by model id.

    The gateway returns the model id as `id`; accepting `model_id` too keeps
    this from breaking if that ever changes shape.
    """
    out: dict[str, ModelRate] = {}
    for row in (raw or []):
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or row.get("model_id") or "").strip()
        if not mid:
            continue
        out[mid] = ModelRate(
            model_id=mid,
            tier=str(row.get("tier") or "").strip().lower(),
            input_cost_per_1k=float(row.get("input_cost_per_1k") or 0),
            output_cost_per_1k=float(row.get("output_cost_per_1k") or 0),
            is_available=bool(row.get("is_available", True)),
        )
    return out


def resolve_slot(
    purpose: str,
    label: str,
    cfg: dict,
    rates: dict[str, ModelRate],
    fees: dict[str, int],
    *,
    allowlist: Optional[list[str]] = None,
) -> ResolvedSlot:
    """Resolve ONE purpose slot exactly the way the kernel's cascade does.

    The rule, verbatim from the config the panel writes: a slot holds a model
    id, and a BLANK slot inherits the global default. That single line is why
    "I pinned one model" and "several different models ran" are both true at
    once -- pinning the global default does not pin a slot that has its own
    value.
    """
    configured = str(cfg.get(f"{purpose}_model") or "").strip()
    global_default = str(cfg.get("model") or "").strip()

    if configured:
        effective, source = configured, "explicit"
    elif global_default:
        effective, source = global_default, "inherited_default"
    else:
        effective, source = "", "unset"

    provider = str(
        cfg.get(f"{purpose}_provider")
        or (cfg.get("provider") if source != "explicit" else "")
        or ""
    ).strip()
    # Every provider field in the config is documented as "auto-inferred from
    # the model id when left blank". Mirror that here, otherwise diagnostics
    # report an empty provider for a slot that will really call Anthropic.
    if not provider and effective:
        provider = _provider_for_model(effective)

    rate = rates.get(effective) if effective else None
    if rate and rate.tier:
        tier, is_priced, available = rate.tier, True, rate.is_available
    else:
        tier, is_priced, available = UNKNOWN_TIER, False, True

    fee = int(fees.get(tier, 0)) if is_priced else 0

    warnings: list[str] = []
    if not effective:
        warnings.append(
            f"No model resolves for '{purpose}' — neither the slot nor the global default is set."
        )
    if effective and not is_priced:
        warnings.append(
            f"'{effective}' has no rate row, so its billing tier is unknown. "
            f"Add one in LLM Pricing before relying on this slot."
        )
    if rate and not rate.is_available:
        warnings.append(
            f"'{effective}' is marked unavailable in LLM Pricing but is still wired to '{purpose}'."
        )
    if tier == "premium" and purpose in ("resolve", "execution", "routing"):
        warnings.append(
            f"'{purpose}' runs on EVERY turn/automation and sits on the premium tier "
            f"({fee} credits per action) — the single biggest driver of a large bill."
        )
    if allowlist is not None and effective and effective not in allowlist:
        warnings.append(
            f"'{effective}' is NOT in the allowed-models list, yet '{purpose}' is wired to it."
        )

    return ResolvedSlot(
        purpose=purpose,
        label=label,
        configured_model=configured,
        effective_model=effective,
        provider=provider,
        source=source,
        tier=tier,
        platform_fee=fee,
        is_available=available,
        is_priced=is_priced,
        warnings=warnings,
    )


def estimate_run_cost(fee: int, actions: int, category: str = "read",
                      category_prices: Optional[dict[str, int]] = None) -> int:
    """Credits for one run: actions x (tier platform fee + function base price).

    The formula the billing path actually uses. Exposed so the operator can be
    shown WHY a run cost what it did, instead of being asked to trust a number.
    """
    prices = category_prices or DEFAULT_CATEGORY_PRICES
    base = int(prices.get(category, prices.get("read", 1)))
    return max(0, int(actions)) * (int(fee) + base)
