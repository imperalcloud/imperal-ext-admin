# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — SYSTEM domain (health, automation rules, confirmation
policy, task limits, LLM connection test).

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys (verified against handlers_system.py + handlers_llm.py). 100%
SDL — the rules list is a real ``sdl.EntityList[T]``; system_health is a real
``sdl.Entity`` whose fields match the REAL runtime keys.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- system health ---

class SystemHealthRecord(sdl.Entity):
    """system_health return shape — a single system-health entity
    (kind='systemhealth').

    The handler returns EXACTLY ``{auth_gateway, registry}`` (verified vs
    handlers_system.fn_system_health: ``data=results`` where results has only
    those two keys). The old SystemHealthResponse keys ``overall`` and
    ``services`` were PHANTOM and are removed."""
    auth_gateway: Optional[Any] = None
    registry: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", "system_health")
            data.setdefault("title", "System health")
            data.setdefault("kind", "systemhealth")
            ag, rg = data.get("auth_gateway"), data.get("registry")
            if ag is not None and rg is not None:
                healthy = ag == "operational" and rg == "operational"
                data.setdefault("status", "operational" if healthy else "degraded")
        return data


# Backward-compatible alias for the old name; 100% SDL (no plain BaseModel).
SystemHealthResponse = SystemHealthRecord


# --- automation rules ---

class RuleRecord(sdl.Entity):
    """A single automation rule as a canonical SDL entity (kind='rule').

    Rule dicts come from the gateway automations API (/v1/automations/...).
    id = rule id (or rule_id); title = name|description|prompt. Known keys kept
    verbatim; complex/optional fields are Optional[Any]. delete/pause/resume key
    on ``rule_id`` (an int), so it is preserved alongside ``id``."""
    rule_id: Optional[Any] = None
    name: Optional[Any] = None
    prompt: Optional[Any] = None
    user_id: Optional[str] = None
    status: Optional[str] = None
    trigger_count: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    max_per_hour: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or data.get("rule_id") or ""
            data.setdefault(
                "title",
                data.get("name") or data.get("description")
                or data.get("prompt") or str(data.get("id") or data.get("rule_id") or ""),
            )
            data.setdefault("kind", "rule")
        return data


class AdminRulesListResponse(sdl.EntityList[RuleRecord]):
    """list_rules return shape — a REAL sdl.EntityList[RuleRecord] (items=[...]).
    The handler keeps ``my_rules_count`` as an extra typed field (additive on
    the pydantic EntityList). NO legacy {rules:[dict],total,my_rules_count}
    wrapper."""
    my_rules_count: int = 0


class RuleActionReceipt(sdl.Entity):
    """Receipt entity for rule write/destructive verbs that return a small
    payload keyed by rule_id (create_rule, delete_rule, pause_rule, resume_rule)
    — kind='rule'. Keeps each observed receipt key verbatim
    (rule payload / deleted / paused / resumed / rule_id). Reuse rather than
    inventing a per-verb receipt."""
    rule: Optional[Any] = None
    rule_id: Optional[Any] = None
    deleted: Optional[bool] = None
    paused: Optional[bool] = None
    resumed: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            _rule = data.get("rule")
            inner = _rule if isinstance(_rule, dict) else {}
            data["id"] = data.get("rule_id") or inner.get("id") or ""
            data.setdefault(
                "title",
                inner.get("name") or inner.get("prompt")
                or str(data.get("rule_id") or ""),
            )
            data.setdefault("kind", "rule")
        return data


# --- confirmation policy / task limits ---

class ConfirmationPolicyResponse(sdl.Entity):
    """get_confirmation_policy return shape — a single role-policy entity."""
    role: str
    policy: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("role") or "")
            data.setdefault("title", data.get("role") or "")
            data.setdefault("kind", "role")
        return data


class UserConfirmationResponse(sdl.Entity):
    """get_user_confirmation return shape — a single user-confirmation entity."""
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    enabled: Optional[bool] = None
    skip_read: Optional[bool] = None
    role_policy: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("user_id") or "")
            data.setdefault("title", data.get("email") or data.get("user_id") or "")
            data.setdefault("kind", "user")
        return data


class TaskLimitResponse(sdl.Entity):
    """get_task_limit return shape — a single role task-limit entity."""
    role: str
    max_tasks: int

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("role") or "")
            data.setdefault("title", data.get("role") or "")
            data.setdefault("kind", "role")
        return data


# --- llm ---

class LLMTestResultRecord(sdl.Entity):
    """test_llm_connection return shape — a single connection-test entity."""
    success: Optional[bool] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data.setdefault("id", data.get("model") or data.get("provider") or "")
            data.setdefault("title", data.get("model") or data.get("provider") or "")
            data.setdefault("kind", "llmtestresult")
        return data


class LLMConfigReceipt(sdl.Entity):
    """Receipt entity for save_llm_config (kind='llmconfig').

    save_llm_config returns one of three observed shapes (verified vs
    handlers_llm.fn_save_llm_config): the generic save
    ``{saved, tenant_defaults_updated, config}``, the override-set
    ``{override, model}``, or the override-reset ``{reset}``. Every observed key
    is kept verbatim so $REF / panels read the same data. id = model (when an
    override model is set) else a stable 'llm_config' handle."""
    saved: Optional[Any] = None
    reset: Optional[str] = None
    override: Optional[str] = None
    model: Optional[str] = None
    tenant_defaults_updated: Optional[Any] = None
    config: Optional[dict] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("model") or data.get("id") or "llm_config"
            data.setdefault("title", data.get("model") or "LLM config")
            data.setdefault("kind", "llmconfig")
        return data


class LLMModelRateReceipt(sdl.Entity):
    """Receipt entity for save_llm_model_rate / delete_llm_model_rate
    (kind='llmmodelrate').

    Mirrors the ACTUAL handler return keys verbatim (verified vs
    handlers_pricing.fn_save_llm_model_rate / fn_delete_llm_model_rate):
    {model_id, action}. id = title = model_id."""
    model_id: Optional[str] = None
    action: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("model_id") or data.get("id") or "llm_model_rate"
            data.setdefault("title", data.get("model_id") or "llm_model_rate")
            data.setdefault("kind", "llmmodelrate")
        return data


# --- system pricing ---

class PlatformFeeReceipt(sdl.Entity):
    """Receipt for save_platform_fees (kind='platformfee').
    Mirrors handler return keys verbatim: {economy, standard, premium, action}."""
    economy: Optional[int] = None
    standard: Optional[int] = None
    premium: Optional[int] = None
    action: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or "platform_fees"
            data.setdefault("title", "Platform Fees")
            data.setdefault("kind", "platformfee")
        return data


class TokenRateReceipt(sdl.Entity):
    """Receipt for save_token_rate (kind='tokenrate').
    Mirrors handler return keys verbatim: {token_rate, action}."""
    token_rate: Optional[int] = None
    action: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or "token_rate"
            data.setdefault("title", "Credit Rate")
            data.setdefault("kind", "tokenrate")
        return data
