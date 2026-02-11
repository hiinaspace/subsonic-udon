#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
since_timestamp_utc="${1:-}"
max_groups="${2:-200}"

payload="$(python3 -c 'import json,sys
print(json.dumps({"sinceTimestampUtc": sys.argv[1], "maxGroups": int(sys.argv[2])}))
' "$since_timestamp_utc" "$max_groups")"

"$script_dir/unity-bridge-curl.sh" logs/since "$payload"
