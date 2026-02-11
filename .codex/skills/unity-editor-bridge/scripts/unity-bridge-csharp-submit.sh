#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <code-file> [timeout-ms]" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
code_file="$1"
timeout_ms="${2:-30000}"

if [[ ! -f "$code_file" ]]; then
  echo "code file not found: $code_file" >&2
  exit 2
fi

payload="$(python3 -c 'import json,pathlib,sys
code = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
print(json.dumps({"code": code, "timeoutMs": int(sys.argv[2])}))
' "$code_file" "$timeout_ms")"

"$script_dir/unity-bridge-curl.sh" csharp/submit "$payload"
