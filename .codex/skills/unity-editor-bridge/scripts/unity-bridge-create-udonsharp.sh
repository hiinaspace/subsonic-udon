#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <path> [contents-file]" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
path="$1"
contents_file="${2-}"

if [[ -n "$contents_file" ]]; then
  if [[ ! -f "$contents_file" ]]; then
    echo "contents file not found: $contents_file" >&2
    exit 2
  fi

  payload="$(python3 - <<'PY' "$path" "$contents_file"
import json, pathlib, sys
path = sys.argv[1]
contents = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
print(json.dumps({"path": path, "contents": contents}))
PY
)"
else
  payload="$(python3 - <<'PY' "$path"
import json, sys
print(json.dumps({"path": sys.argv[1]}))
PY
)"
fi

"$script_dir/unity-bridge-curl.sh" udonsharp/create-script "$payload"
