#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAYTRACK_HOST="${PLAYTRACK_HOST:-127.0.0.1}"

cleanup() {
  trap - EXIT INT TERM
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/backend"
  uv run uvicorn app.main:app --reload --host "$PLAYTRACK_HOST" --port 8000
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  npm run dev
) &
FRONTEND_PID=$!

echo "PlayTrack backend: http://${PLAYTRACK_HOST}:8000"
echo "PlayTrack frontend: http://127.0.0.1:5173"
echo "Press Ctrl+C to stop both servers."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

echo "One PlayTrack process stopped; shutting down the other."
cleanup
wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit 1
