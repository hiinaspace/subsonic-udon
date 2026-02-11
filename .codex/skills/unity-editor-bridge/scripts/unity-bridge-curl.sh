#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <endpoint> [json-body]" >&2
  exit 2
fi

base_url="${UNITY_BRIDGE_URL:-http://127.0.0.1:32190}"
endpoint="$1"
body="${2-}"
url="${base_url%/}/${endpoint#/}"

if [[ -n "$body" ]]; then
  curl -sS -X POST "$url" -H 'Content-Type: application/json' -d "$body"
else
  curl -sS "$url"
fi
