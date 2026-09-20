#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
backend_python="$project_root/backend/.venv/bin/python"

if [[ ! -x "$backend_python" ]]; then
  echo "Backend environment is missing. Run: make setup-backend" >&2
  exit 1
fi

if [[ ! -d "$project_root/credit-passport-ui/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run: cd credit-passport-ui && npm ci" >&2
  exit 1
fi

backend_pid=""
frontend_pid=""

cleanup() {
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$project_root/backend"
  exec .venv/bin/uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
) &
backend_pid=$!

(
  cd "$project_root/credit-passport-ui"
  exec npm run dev -- --host 127.0.0.1 --port 5173
) &
frontend_pid=$!

echo "Credit Passport API: http://127.0.0.1:8000/docs"
echo "Credit Passport app: http://127.0.0.1:5173"

wait "$backend_pid" "$frontend_pid"
