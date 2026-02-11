#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
since_id="${1:-0}"
max_groups="${2:-200}"

payload="{\"sinceId\":${since_id},\"maxGroups\":${max_groups}}"
"$script_dir/unity-bridge-curl.sh" logs/since "$payload"
