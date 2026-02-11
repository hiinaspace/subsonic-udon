#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <job-id>" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
job_id="$1"

payload="$(python3 -c 'import json,sys
print(json.dumps({"jobId": sys.argv[1]}))
' "$job_id")"

"$script_dir/unity-bridge-curl.sh" csharp/job "$payload"
