# imperal-ext-admin

Administrative control plane — manage users, roles, RBAC scopes, billing limits, payment plans, extension installs, LLM model configuration, and tenant-wide settings.

Imperal-owned system extension for [Webbee 🐝](https://docs.imperal.io), the agent of [Imperal Cloud](https://imperal.io) — the AI Cloud OS.

| Field | Value |
|---|---|
| **App ID** | `admin` |
| **Current version** | `5.9.1` |
| **Status** | Production |
| **License** | Proprietary (Imperal, Inc.) |
| **SDK** | `imperal-sdk 5.8.0` |
| **Manifest schema** | `3` |
| **actions_explicit** | `true` |
| **System app** | `true` |
| **Chat tools** | `92` |
| **Capabilities** | `28` |

## What this extension owns

The Admin extension is the platform control plane. In this repo it is organised into four main layers:

- `app.py` — shared extension state, gateway/registry helpers, health check, lifecycle hooks
- `main.py` — deterministic import/registration entrypoint for validators and runtime
- `handlers_*.py` — admin chat functions and write/read operations
- `panels_*.py` + `panels.py` — declarative admin UI routed through sidebar + center tools panel
- `models_*.py` — Pydantic contracts / SDL return shapes
- `skeleton.py` — background admin dashboard snapshot producer

## UI architecture

The panel surface is intentionally split into:

- `sidebar` (`slot="left"`) — section navigation
- `tools` (`slot="center"`, `center_overlay=True`) — active admin workspace

Routing rules:

- `active` is the canonical sidebar-selected section
- `section` is used for cross-section jumps from inside another panel
- the tools router gives `section` higher priority than `active`
- sidebar clicks explicitly send `section=""` to clear stale sub-view state

This pattern is important for Imperal's panel host param-merge behavior and should be preserved.

## Deploy flow

This git repo is the source of truth. The deployed worker copy is downstream of developer/admin deployment flows and should not be edited directly.

1. Edit code locally in this folder.
2. Run local validation (`python3 -m py_compile *.py` at minimum).
3. Commit and push to the tracked branch.
4. Open the Imperal panel at `https://panel.imperal.io`, then go to Developer if you need to deploy a new build.
5. Dev Portal / validator checks the extension contract before rollout.

## Current audit notes

Confirmed from the live source in this folder:

- manifest version matches runtime version: `5.9.1`
- SDK target matches manifest: `5.8.0`
- manifest declares `92` tools and `28` capabilities
- local module compile check passes

## Federal contract

Must satisfy the applicable Imperal extension validator contract before publish/redeploy. Primary reference:

- <https://docs.imperal.io/en/sdk/validators-reference/>
