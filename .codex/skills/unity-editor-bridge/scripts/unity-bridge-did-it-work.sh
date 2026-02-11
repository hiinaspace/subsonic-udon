#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
settle_ms="${1:-500}"
timeout_ms="${2:-15000}"
max_groups="${3:-200}"
recovery_wait_seconds="${4:-20}"

payload="{\"settleMs\":${settle_ms},\"timeoutMs\":${timeout_ms},\"maxGroups\":${max_groups}}"

before_health="$("$script_dir/unity-bridge-health.sh" 2>/dev/null || true)"
before_id="$(python3 -c 'import json,sys
raw=sys.argv[1]
if not raw.strip():
    print(0)
else:
    try:
        obj=json.loads(raw)
        print(int(obj.get("lastLogId",0)))
    except Exception:
        print(0)
' "$before_health")"

tmp_err="$(mktemp)"
trap 'rm -f "$tmp_err"' EXIT

if did_it_work_json="$("$script_dir/unity-bridge-curl.sh" did-it-work "$payload" 2>"$tmp_err")"; then
  printf '%s\n' "$did_it_work_json"
  exit 0
fi

echo "[unity-bridge-did-it-work] request dropped, waiting for bridge reload..." >&2

for _ in $(seq 1 "$recovery_wait_seconds"); do
  if "$script_dir/unity-bridge-health.sh" >/dev/null 2>&1; then
    logs_json="$("$script_dir/unity-bridge-logs-since.sh" "$before_id" "$max_groups")"
    python3 -c 'import json,sys
before_id=int(sys.argv[1])
logs=json.loads(sys.argv[2])
out={
  "ok": True,
  "fallback": True,
  "note": "did-it-work disconnected during refresh; returned logs/since after bridge recovery",
  "beforeId": before_id,
  "afterId": int(logs.get("lastLogId", before_id)),
  "newLogGroups": logs.get("logGroups", []),
  "compileState": logs.get("compileState", {}),
}
print(json.dumps(out))
' "$before_id" "$logs_json"
    exit 0
  fi
  sleep 1
done

echo "[unity-bridge-did-it-work] bridge did not recover within ${recovery_wait_seconds}s" >&2
cat "$tmp_err" >&2
exit 1
