"""Admin · Webbee's proactivity — the admin's master switch.

STORE OF TRUTH: the gateway's settings layers (Unified Config Store), the same
row the kernel's living matrix reads on every tick
(``GET /v1/internal/users/{id}/settings`` -> ``proactivity_enabled``):

  code default (off) < the tenant default (``PATCH /v1/admin/tenant-defaults``)
  < the user's own switch < the admin's LOCK (``proactivity_lock``: "on" / "off",
  at the tenant or for one user; "" = no lock).

The user turns it on or off themselves (``/v1/me/settings``) unless an admin's
lock holds it; the gateway refuses a lock without an admin in X-Acting-User.
Spec: kernel docs/superpowers/specs/2026-10-28-living-matrix-design.md.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app import chat, ActionResult, _acting, _gw_request, _tenant_id
from models_system import ProactivityResponse

LOCKS = ("on", "off", "")


class TenantProactivityParams(BaseModel):
    """Set Webbee's proactivity for everyone in the tenant."""
    enabled: Optional[bool] = Field(default=None, description="The tenant default: on or off (users may change theirs)")
    lock: Optional[str] = Field(default=None, description='Master lock for everyone: "on", "off", or "" to unlock')


class UserProactivityParams(BaseModel):
    """Set Webbee's proactivity for one user."""
    user_id: str = Field(description="User imperal_id")
    enabled: Optional[bool] = Field(default=None, description="On or off for this user")
    lock: Optional[str] = Field(default=None, description='Master lock for this user: "on", "off", or "" to unlock')


class ProactivityReadParams(BaseModel):
    """Read Webbee's proactivity: the tenant's, and one user's when given."""
    user_id: Optional[str] = Field(default=None, description="User imperal_id (omit for the tenant only)")


def _patch(params) -> dict:
    out = {}
    if params.enabled is not None:
        out["proactivity_enabled"] = bool(params.enabled)
    if params.lock is not None:
        out["proactivity_lock"] = params.lock
    return out


def _state(settings: dict) -> dict:
    s = settings or {}
    return {"enabled": bool(s.get("proactivity_enabled")), "lock": str(s.get("proactivity_lock") or ""),
            "user_can_change": bool(s.get("_proactivity_user_can_change", True))}


@chat.function("set_proactivity", action_type="write", effects=["update:proactivity"], event="proactivity_set",
               data_model=ProactivityResponse,
               description="Turn Webbee's proactivity on or off for the whole tenant (the default users start from), "
                           "and/or lock it for everyone (master switch: lock on/off, \"\" unlocks).")
async def fn_set_proactivity(ctx, params: TenantProactivityParams) -> ActionResult:
    """The tenant default and the tenant-wide lock -- verified by reading them back."""
    patch = _patch(params)
    if not patch:
        return ActionResult.error("Nothing to set: give enabled and/or lock")
    if params.lock is not None and params.lock not in LOCKS:
        return ActionResult.error('lock must be "on", "off" or "" (unlock)')
    tenant = _tenant_id(ctx)
    result = await _gw_request("PATCH", f"/v1/admin/tenant-defaults?tenant_id={tenant}", patch, acting=_acting(ctx))
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    check = await _gw_request("GET", f"/v1/admin/tenant-defaults?tenant_id={tenant}")
    got = (check.get("settings") or {}) if isinstance(check, dict) and not check.get("error") else {}
    for key, want in patch.items():
        if got.get(key) != want:
            return ActionResult.error(f"proactivity did not persist: {key} asked {want!r}, gateway has {got.get(key)!r}")
    st = _state(got)
    return ActionResult.success(
        data={"scope": "tenant", "tenant_id": tenant, **st},
        summary=f"Tenant proactivity: {'on' if st['enabled'] else 'off'}"
                + (f", locked {st['lock']}" if st["lock"] else ", users may change theirs"),
        refresh_panels=["tools"])


@chat.function("set_user_proactivity", action_type="write", effects=["update:proactivity"], event="proactivity_set",
               data_model=ProactivityResponse,
               description="Turn Webbee's proactivity on or off for ONE user, and/or lock it for them "
                           "(master switch: lock on/off overrides the user's own choice, \"\" unlocks).")
async def fn_set_user_proactivity(ctx, params: UserProactivityParams) -> ActionResult:
    """One user's switch and lock -- the effective value read back is what the kernel will see."""
    patch = _patch(params)
    if not patch:
        return ActionResult.error("Nothing to set: give enabled and/or lock")
    if params.lock is not None and params.lock not in LOCKS:
        return ActionResult.error('lock must be "on", "off" or "" (unlock)')
    result = await _gw_request("PATCH", f"/v1/internal/users/{params.user_id}/settings", patch, acting=_acting(ctx))
    if isinstance(result, dict) and result.get("error"):
        return ActionResult.error(result["error"])
    check = await _gw_request("GET", f"/v1/internal/users/{params.user_id}/settings?tenant_id={_tenant_id(ctx)}")
    got = (check.get("settings", check) or {}) if isinstance(check, dict) and not check.get("error") else {}
    st = _state(got)
    want = {"on": True, "off": False}.get(str(patch.get("proactivity_lock") or ""), patch.get("proactivity_enabled"))
    if got and want is not None and st["enabled"] != bool(want):
        return ActionResult.error(f"proactivity did not persist for {params.user_id} (asked {want}, "
                                  f"gateway reports {st['enabled']})")
    return ActionResult.success(
        data={"scope": "user", "user_id": params.user_id, **st},
        summary=f"{params.user_id} proactivity: {'on' if st['enabled'] else 'off'}"
                + (f" (locked {st['lock']})" if st["lock"] else ""),
        refresh_panels=["tools"])


@chat.function("get_proactivity", action_type="read", data_model=ProactivityResponse,
               description="Show Webbee's proactivity: the tenant default and lock, and one user's effective value.")
async def fn_get_proactivity(ctx, params: ProactivityReadParams) -> ActionResult:
    tenant = _tenant_id(ctx)
    t = await _gw_request("GET", f"/v1/admin/tenant-defaults?tenant_id={tenant}")
    if isinstance(t, dict) and t.get("error"):
        return ActionResult.error(t["error"])
    ts = (t.get("settings") or {}) if isinstance(t, dict) else {}
    data = {"scope": "tenant", "tenant_id": tenant, "enabled": bool(ts.get("proactivity_enabled")),
            "lock": str(ts.get("proactivity_lock") or "")}
    summary = f"Tenant: {'on' if data['enabled'] else 'off'}" + (f", locked {data['lock']}" if data["lock"] else "")
    if params.user_id:
        u = await _gw_request("GET", f"/v1/internal/users/{params.user_id}/settings?tenant_id={tenant}")
        if isinstance(u, dict) and u.get("error"):
            return ActionResult.error(u["error"])
        st = _state((u.get("settings", u) or {}) if isinstance(u, dict) else {})
        data = {"scope": "user", "user_id": params.user_id, "tenant_enabled": data["enabled"],
                "tenant_lock": data["lock"], **st}
        summary += f"; {params.user_id}: {'on' if st['enabled'] else 'off'}" + \
            (f" (locked {st['lock']})" if st["lock"] else "" if st["user_can_change"] else " (locked)")
    return ActionResult.success(data=data, summary=summary)
