"""Admin · Reset context defaults handler (split to keep handlers_system.py <300L)."""
from __future__ import annotations

import logging

from app import chat, ActionResult, _gw_request

log = logging.getLogger("admin")

# Built-in platform defaults (match React CONTEXT_FIELDS defaultValues)
_BUILTIN_DEFAULTS = {
    "quality_ceiling_tokens": 50000,
    "default_context_window": 20,
    "default_max_tool_rounds": 10,
    "default_max_result_tokens": 3000,
    "default_keep_recent": 6,
    "list_truncate_items": 10,
    "string_truncate_chars": 1500,
    "max_history_stored": 40,
    "history_ttl_days": 7,
}


@chat.function("reset_context_defaults", action_type="destructive",
               description="Reset platform context defaults to built-in values.")
async def fn_reset_context_defaults(ctx) -> ActionResult:
    """Reset context defaults via Auth GW platform config (same as React)."""
    try:
        raw = await _gw_request("GET", "/v1/internal/config/platform/platform")
        current_config = raw.get("config", {}) if isinstance(raw, dict) else {}
        current_config["context_defaults"] = dict(_BUILTIN_DEFAULTS)

        await _gw_request("PUT", "/v1/internal/config/platform/platform",
                          {"config": current_config})

        return ActionResult.success(
            data={"reset": True, "defaults": _BUILTIN_DEFAULTS},
            summary="Context defaults reset to platform built-in values",
        )
    except Exception as e:
        log.error("reset_context_defaults failed: %s", e)
        return ActionResult.error(f"Failed to reset: {e}", retryable=True)
