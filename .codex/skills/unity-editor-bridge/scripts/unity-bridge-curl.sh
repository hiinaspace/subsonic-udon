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
max_attempts="${UNITY_BRIDGE_RETRY_ATTEMPTS:-25}"
sleep_seconds="${UNITY_BRIDGE_RETRY_SLEEP_SECONDS:-0.5}"
connect_timeout="${UNITY_BRIDGE_CONNECT_TIMEOUT_SECONDS:-2}"
request_timeout="${UNITY_BRIDGE_REQUEST_TIMEOUT_SECONDS:-120}"

if ! [[ "$max_attempts" =~ ^[0-9]+$ ]] || [[ "$max_attempts" -lt 1 ]]; then
  echo "invalid UNITY_BRIDGE_RETRY_ATTEMPTS: $max_attempts" >&2
  exit 2
fi

tmp_err="$(mktemp)"
trap 'rm -f "$tmp_err"' EXIT

for ((attempt=1; attempt<=max_attempts; attempt++)); do
  set +e
  if [[ -n "$body" ]]; then
    curl -sS --fail \
      --connect-timeout "$connect_timeout" \
      --max-time "$request_timeout" \
      -X POST "$url" -H 'Content-Type: application/json' -d "$body" 2>"$tmp_err"
    curl_exit="$?"
  else
    curl -sS --fail \
      --connect-timeout "$connect_timeout" \
      --max-time "$request_timeout" \
      "$url" 2>"$tmp_err"
    curl_exit="$?"
  fi
  set -e

  if [[ "$curl_exit" -eq 0 ]]; then
    exit 0
  fi

  curl_err="$(cat "$tmp_err")"
  retryable=false

  case "$curl_exit" in
    7|22|28|52|56)
      retryable=true
      ;;
  esac

  if [[ "$curl_exit" -eq 22 ]]; then
    if [[ "$curl_err" != *" 502"* && "$curl_err" != *" 503"* && "$curl_err" != *" 504"* ]]; then
      retryable=false
    fi
  fi

  if [[ "$retryable" != true || "$attempt" -eq "$max_attempts" ]]; then
    echo "$curl_err" >&2
    exit "$curl_exit"
  fi

  sleep "$sleep_seconds"
done
