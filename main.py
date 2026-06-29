"""Admin v5.2.6 · Platform administration for Imperal Cloud."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
# Force re-import of every admin module on each load — otherwise the validator's
# double-load pass (used by the Dev Portal's `validate_extension_deep.py`) sees
# cached @chat.function decorators bound to a stale ChatExtension, and the new
# Extension's `_chat_extensions[*]._functions` is missing those entries, which
# surfaces as a spurious "In manifest but not code" drift warning. Wildcard
# match keeps the clearing list automatically in sync with new modules.
for _m in [k for k in list(sys.modules) if k == "app" or k.startswith(("handlers_", "panels_", "models_", "skeleton"))]:
    del sys.modules[_m]
for _m in ("handlers", "panels", "skeleton"):
    sys.modules.pop(_m, None)

from app import ext, chat  # noqa: F401

import handlers_users          # noqa: F401
import handlers_roles          # noqa: F401
import handlers_rbac           # noqa: F401
import handlers_extensions     # noqa: F401
import handlers_ext_settings   # noqa: F401
import handlers_system         # noqa: F401
import handlers_llm            # noqa: F401
import handlers_pricing        # noqa: F401  # Sprint 4 LLM rate CRUD
import panels_pricing          # noqa: F401  # Sprint 4 LLM Pricing panel
import handlers_system_pricing  # noqa: F401  # System Pricing: fee + credit-rate write handlers
import panels_system_pricing    # noqa: F401  # System Pricing panel
import handlers_voice          # noqa: F401  # Voice: pricing/master/role-access handlers
import panels_voice            # noqa: F401  # Voice panel
import handlers_billing        # noqa: F401
import handlers_payment        # noqa: F401
import handlers_developer      # noqa: F401
import handlers_admin_reads    # noqa: F401  # Webbee read-gaps: payments/cards/limits/agencies/pending-apps/pending-payouts
import handlers_email          # noqa: F401  # Email tab: durable log + per-case template control + test send
import skeleton                # noqa: F401
import panels                  # noqa: F401
