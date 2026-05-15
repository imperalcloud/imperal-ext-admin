"""Admin · Skeleton tools (V13 @ext.skeleton decorator)."""
from __future__ import annotations

import httpx

from app import ext, AUTH_GW, REGISTRY_URL, _gw_request, _registry_get


# ─── Skeleton ─────────────────────────────────────────────────────────── #

@ext.skeleton(
    "admin_stats",
    alert=True,
    description="Background refresh for admin dashboard.",
)
async def on_skeleton_refresh(ctx, **kwargs) -> dict:
    stats: dict = {}
    try:
        raw = await _gw_request(ctx, "GET", "/v1/users?include_inactive=true")
        users = raw.get("items", raw) if isinstance(raw, dict) else raw
        if isinstance(users, list):
            stats["users_total"] = len(users)
            stats["users_active"] = sum(1 for u in users if u.get("is_active"))
            stats["users_admins"] = sum(1 for u in users if u.get("role") == "admin")
            stats["users_list"] = [
                {"id": u.get("imperal_id"), "email": u.get("email"), "role": u.get("role"), "active": u.get("is_active")}
                for u in users
            ]
    except Exception:
        stats["users_total"] = 0
    try:
        roles = await _gw_request(ctx, "GET", "/v1/roles")
        stats["roles_count"] = len(roles) if isinstance(roles, list) else 0
    except Exception:
        stats["roles_count"] = 0
    try:
        r = await _registry_get(ctx, "/v1/apps?status=active")
        apps = r.json() if r.status_code == 200 else []
        stats["extensions_active"] = len(apps) if isinstance(apps, list) else 0
    except Exception:
        stats["extensions_active"] = 0
    for name, url in [("auth_gateway", f"{AUTH_GW}/healthz"), ("registry", f"{REGISTRY_URL}/health")]:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(url)
                stats[f"health_{name}"] = "operational" if r.status_code == 200 else "down"
        except Exception:
            stats[f"health_{name}"] = "unreachable"

    return {"response": stats}


# Paired alert tool (must remain @ext.tool — the V13 decorator only declares the
# refresh side; the kernel auto-discovers ``skeleton_alert_<section>`` by naming
# convention when alert=True is set on the matching @ext.skeleton call).
@ext.tool("skeleton_alert_admin_stats", description="Alert on admin dashboard changes.")
async def on_skeleton_alert(ctx, **kwargs) -> str:
    old, new = kwargs.get("old", {}), kwargs.get("new", {})
    alerts = []
    if new.get("users_total", 0) > old.get("users_total", 0) > 0:
        alerts.append(f"{new['users_total'] - old['users_total']} new user(s).")
    for svc in ["auth_gateway", "registry"]:
        oh, nh = old.get(f"health_{svc}"), new.get(f"health_{svc}")
        if oh and nh and oh != nh:
            alerts.append(f"**{svc}**: {oh} -> {nh}")
    return "\n".join(alerts) if alerts else ""
