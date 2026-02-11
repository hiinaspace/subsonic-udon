---
name: unity-editor-bridge
description: Operate a local Unity Editor HTTP bridge for agent workflows without MCP. Use when working in this repo and you need to check editor state, refresh/recompile and inspect logs, or create UdonSharp script plus matching UdonSharpProgramAsset through bridge endpoints.
---

# Unity Editor Bridge

Use this skill to drive the local Unity bridge at `http://127.0.0.1:32190` (override with `UNITY_BRIDGE_URL`).

## Workflow

1. Check connectivity with `scripts/unity-bridge-health.sh`.
2. After file edits, call `scripts/unity-bridge-did-it-work.sh`.
3. For incremental logs, call `scripts/unity-bridge-logs-since.sh <since_id>`.
4. To create a UdonSharp script + `.asset`, call `scripts/unity-bridge-create-udonsharp.sh <path> [contents-file]`.

## Notes

- Bridge endpoints are local-only and unauthenticated by design for this repo.
- If calls fail after code edits, focus Unity Editor and wait for compile/reload, then retry.
- Prefer `did-it-work` after edits because it refreshes assets and returns post-refresh logs.
- Unity refresh can domain-reload the editor and drop an in-flight HTTP response. `unity-bridge-did-it-work.sh` handles this by waiting for bridge recovery and falling back to `logs/since` from the pre-refresh log id.
