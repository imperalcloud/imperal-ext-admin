# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Entity record models for the admin extension — 100% SDL aggregator.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: every record's field names mirror
the ACTUAL runtime dict keys its handler returns (each model was defined by
READING the producing handler — see the per-domain modules for the verification
notes). The kernel reads these schemas for $REF path validation, classifier
envelope rendering, and SDL entity/list detection (``x-sdl`` markers).

SDL migration COMPLETE (2026-06-02, SDK 5.2.0, NO legacy):
  * Every single-result record is a real ``sdl.Entity`` (+ matching facets) with
    a ``mode="before"`` ``_sdl_canon`` that populates canonical id/title/kind
    from the existing id-ish / name-ish keys (OVERWRITING id with the more
    canonical key where one exists), so EXISTING
    ``ActionResult.success(data={...})`` calls keep working unchanged.
  * Every LIST return is a real ``sdl.EntityList[T]`` (``items=[...]``,
    ``x-sdl="entity-list"``). The legacy plain-BaseModel wrappers
    ({users:[dict]}, {roles:[dict]}, {scopes:[str]}, {extensions:[dict]},
    {entries:[dict]}, {plans:[dict]}, {wallets:[dict]}, {rules:[dict]}) are GONE.
    Handlers now return ``data={"items":[...], "total": n, <scalars...>}``.

The file is SPLIT by domain (federal Rule 6 — no god file >300 LOC) and
re-exports EVERYTHING so handlers keep importing ``from models_records import
<Name>`` unchanged:
  * models_users.py        — UserRecord, UserListResponse, ExtensionUsersResponse,
                             UserBalanceRecord, UserBalancesResponse
  * models_roles.py        — RoleRecord, RoleListResponse, RoleActionReceipt,
                             BulkRoleAssignReceipt, ScopeRecord, ScopeListResponse
  * models_developer.py    — AppReviewReceipt, PayoutReviewReceipt,
                             DeveloperProfileRecord, DeveloperTierReceipt
  * models_extensions.py   — ExtensionRecord, ExtensionsListResponse,
                             ExtensionConfigRecord, AccessPolicyRecord,
                             ExtSettingsReceipt
  * models_billing.py      — PlanRecord, BillingOverviewResponse,
                             BillingHealthRecord (== BillingHealthResponse),
                             PaymentConfigRecord, PaymentTestResultRecord
  * models_rbac.py         — AuditEntryRecord, AuditLogResponse,
                             EffectiveScopesResponse, PermissionCheckResponse,
                             CompareRolesResponse
  * models_system.py       — SystemHealthRecord (== SystemHealthResponse),
                             RuleRecord, AdminRulesListResponse, RuleActionReceipt,
                             ConfirmationPolicyResponse, UserConfirmationResponse,
                             TaskLimitResponse, LLMTestResultRecord,
                             LLMConfigReceipt, LLMModelRateReceipt,
                             PlatformFeeReceipt, TokenRateReceipt
"""
from __future__ import annotations

from models_users import (  # noqa: F401
    UserRecord,
    UserListResponse,
    ExtensionUsersResponse,
    UserBalanceRecord,
    UserBalancesResponse,
)
from models_roles import (  # noqa: F401
    RoleRecord,
    RoleListResponse,
    RoleActionReceipt,
    BulkRoleAssignReceipt,
    ScopeRecord,
    ScopeListResponse,
)
from models_developer import (  # noqa: F401
    AppReviewReceipt,
    DeveloperProfileRecord,
    DeveloperTierReceipt,
    PayoutReviewReceipt,
)
from models_extensions import (  # noqa: F401
    ExtensionRecord,
    ExtensionsListResponse,
    ExtensionConfigRecord,
    AccessPolicyRecord,
    ExtSettingsReceipt,
)
from models_billing import (  # noqa: F401
    PlanRecord,
    BillingOverviewResponse,
    BillingHealthRecord,
    BillingHealthResponse,
    PaymentConfigRecord,
    PaymentTestResultRecord,
)
from models_rbac import (  # noqa: F401
    AuditEntryRecord,
    AuditLogResponse,
    EffectiveScopesResponse,
    PermissionCheckResponse,
    CompareRolesResponse,
)
from models_system import (  # noqa: F401
    SystemHealthRecord,
    SystemHealthResponse,
    RuleRecord,
    AdminRulesListResponse,
    RuleActionReceipt,
    ConfirmationPolicyResponse,
    UserConfirmationResponse,
    TaskLimitResponse,
    LLMTestResultRecord,
    LLMConfigReceipt,
    LLMModelRateReceipt,
    PlatformFeeReceipt,
    TokenRateReceipt,
    CategoryDefaultsReceipt,
    CodingPricingReceipt,
)

__all__ = [
    # users
    "UserRecord", "UserListResponse", "ExtensionUsersResponse",
    "UserBalanceRecord", "UserBalancesResponse",
    # roles & scopes
    "RoleRecord", "RoleListResponse", "RoleActionReceipt", "BulkRoleAssignReceipt",
    "ScopeRecord", "ScopeListResponse",
    # developer portal
    "AppReviewReceipt", "PayoutReviewReceipt",
    "DeveloperProfileRecord", "DeveloperTierReceipt",
    # extensions
    "ExtensionRecord", "ExtensionsListResponse", "ExtensionConfigRecord",
    "AccessPolicyRecord", "ExtSettingsReceipt",
    # billing
    "PlanRecord", "BillingOverviewResponse",
    "BillingHealthRecord", "BillingHealthResponse",
    "PaymentConfigRecord", "PaymentTestResultRecord",
    # rbac
    "AuditEntryRecord", "AuditLogResponse", "EffectiveScopesResponse",
    "PermissionCheckResponse", "CompareRolesResponse",
    # system
    "SystemHealthRecord", "SystemHealthResponse", "RuleRecord",
    "AdminRulesListResponse", "RuleActionReceipt", "ConfirmationPolicyResponse",
    "UserConfirmationResponse", "TaskLimitResponse", "LLMTestResultRecord",
    "LLMConfigReceipt", "LLMModelRateReceipt",
    # system pricing
    "PlatformFeeReceipt", "TokenRateReceipt", "CategoryDefaultsReceipt", "CodingPricingReceipt",
]
