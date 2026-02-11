#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <code-file> [job-timeout-ms] [poll-seconds]" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
code_file="$1"
job_timeout_ms="${2:-30000}"
poll_seconds="${3:-1}"

submit_json="$("$script_dir/unity-bridge-csharp-submit.sh" "$code_file" "$job_timeout_ms")"
job_id="$(python3 -c 'import json,sys
obj=json.loads(sys.argv[1])
if not obj.get("ok"):
    raise SystemExit(1)
print(obj["jobId"])
' "$submit_json")"

"$script_dir/unity-bridge-did-it-work.sh" 500 30000 300 30 >/dev/null || true

max_polls=$(( job_timeout_ms / 1000 + 30 ))
if [[ $max_polls -lt 30 ]]; then
  max_polls=30
fi

for ((i=0; i<max_polls; i++)); do
  if ! job_json="$("$script_dir/unity-bridge-csharp-job.sh" "$job_id" 2>/dev/null)"; then
    sleep "$poll_seconds"
    continue
  fi

  status="$(python3 -c 'import json,sys
obj=json.loads(sys.argv[1])
if not obj.get("ok"):
    print("query_error")
else:
    print(obj.get("job", {}).get("status", "unknown"))
' "$job_json")"

  case "$status" in
    succeeded)
      printf '%s\n' "$job_json"
      exit 0
      ;;
    failed|failed_compile|timeout|query_error)
      printf '%s\n' "$job_json"
      exit 1
      ;;
    queued|running|unknown)
      sleep "$poll_seconds"
      ;;
    *)
      sleep "$poll_seconds"
      ;;
  esac

done

echo "Timed out polling csharp job $job_id" >&2
"$script_dir/unity-bridge-csharp-job.sh" "$job_id" || true
exit 1
