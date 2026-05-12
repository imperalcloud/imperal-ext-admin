"""Admin v5.2.6 · Platform administration for Imperal Cloud."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in (
    "app", "handlers_users", "handlers_roles", "handlers_rbac",
    "handlers_extensions", "handlers_ext_settings",
    "handlers_system", "handlers_system_reset",
    "handlers_llm", "handlers_billing", "handlers_payment",
    "handlers_developer",
    "skeleton", "panels", "panels_sections",
    "panels_dashboard", "panels_users", "panels_user_profile",
    "panels_roles", "panels_extensions", "panels_scopes",
    "panels_audit", "panels_llm", "panels_llm_form",
    "panels_ext_settings", "panels_ext_settings_ai",
    "panels_ext_settings_ops", "panels_ext_access_policy",
    "panels_ext_users", "panels_payment",
    "panels_developer", "panels_payouts",
)]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers_users          # noqa: F401
import handlers_roles          # noqa: F401
import handlers_rbac           # noqa: F401
import handlers_extensions     # noqa: F401
import handlers_ext_settings   # noqa: F401
import handlers_system         # noqa: F401
import handlers_system_reset   # noqa: F401
import handlers_llm            # noqa: F401
import handlers_pricing        # noqa: F401  # Sprint 4 LLM rate CRUD
import panels_pricing          # noqa: F401  # Sprint 4 LLM Pricing panel
import handlers_billing        # noqa: F401
import handlers_payment        # noqa: F401
import handlers_developer      # noqa: F401
import skeleton                # noqa: F401
import panels                  # noqa: F401
