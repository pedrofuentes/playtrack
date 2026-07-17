#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FINDME_HOST="${FINDME_HOST:-127.0.0.1}"

cleanup() {
  trap - EXIT INT TERM
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/backend"
  uv run uvicorn app.main:app --reload --host "$FINDME_HOST" --port 8000
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  npm run dev
) &
FRONTEND_PID=$!

echo "FindMe backend: http://${FINDME_HOST}:8000"
echo "FindMe frontend: http://127.0.0.1:5173"
echo "Press Ctrl+C to stop both servers."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

echo "One FindMe process stopped; shutting down the other."
cleanup
wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit 1
