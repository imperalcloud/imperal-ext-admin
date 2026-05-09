# imperal-ext-admin

Administrative control plane — manage users, roles, RBAC scopes, billing limits, payment plans, extension installs, LLM model configuration, and tenant-wide settings.

Imperal-owned extension for [Webbee 🐝](https://docs.imperal.io), the agent of [Imperal Cloud](https://imperal.io) — the world's first AI Cloud OS.

| Field | Value |
|---|---|
| **App ID** | `admin` |
| **Current version** | v5.1.0 |
| **Status** | Production |
| **License** | Proprietary (Imperal, Inc.) |
| **SDK** | `imperal-sdk >= 4.1.4` |

## Deploy flow

This git repo is the **source of truth**. The deployed copy on `whm-ai-worker:/opt/extensions/admin/` is downstream of Dev Portal uploads — do not edit the deployed copy directly.

1. Edit code locally in this folder.
2. Commit + push to `main`.
3. Open <https://panel.imperal.io/developer> and upload a tarball of the current commit.
4. Dev Portal validates against the federal extension contract (V14–V22 + V24) and rolls out to production workers.

## Federal contract

Must satisfy V14–V22 + V24 to publish via Dev Portal. See <https://docs.imperal.io/en/sdk/validators-reference/>.
