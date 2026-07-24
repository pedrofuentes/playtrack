#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/dev.sh [--network]

Start the PlayTrack FastAPI and Vite development servers.

Options:
  --network  Bind both servers to 0.0.0.0 for trusted-LAN access.
  --help     Show this help and exit.
EOF
}

bind_host="${PLAYTRACK_HOST:-127.0.0.1}"

if (( $# > 1 )); then
  printf 'Expected at most one option.\n' >&2
  usage >&2
  exit 2
fi

case "${1:-}" in
  "") ;;
  "--network") bind_host="0.0.0.0" ;;
  "--help") usage; exit 0 ;;
  *)
    printf 'Unknown option: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac

network_mode=0
case "$bind_host" in
  "127.0.0.1"|"localhost"|"::1") ;;
  *) network_mode=1 ;;
esac

wildcard_host=0
case "$bind_host" in
  "0.0.0.0"|"::") wildcard_host=1 ;;
esac

format_url_host() {
  case "$1" in
    *:*) printf '[%s]\n' "$1" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

url_host="$(format_url_host "$bind_host")"

is_private_ipv4() {
  local address="$1"
  local second_octet
  case "$address" in
    10.*|192.168.*) return 0 ;;
    172.*)
      second_octet="${address#172.}"
      second_octet="${second_octet%%.*}"
      [[ "$second_octet" =~ ^[0-9]+$ ]] &&
        (( second_octet >= 16 && second_octet <= 31 ))
      ;;
    *) return 1 ;;
  esac
}

detect_lan_ip() {
  local candidate
  local interface

  if command -v ipconfig >/dev/null 2>&1; then
    for interface in en0 en1; do
      if candidate="$(ipconfig getifaddr "$interface" 2>/dev/null)" &&
        is_private_ipv4 "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  fi

  if command -v hostname >/dev/null 2>&1; then
    while IFS= read -r candidate; do
      if is_private_ipv4 "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done < <(hostname -I 2>/dev/null | tr ' ' '\n' || true)
  fi

  return 1
}

cleanup() {
  trap - EXIT INT TERM
  kill "${backend_pid:-}" "${frontend_pid:-}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(
  cd "$root_dir/backend"
  exec uv run uvicorn app.main:app --reload --host "$bind_host" --port 8000
) &
backend_pid=$!

(
  cd "$root_dir/frontend"
  exec npm run dev -- --host "$bind_host" --port 5173
) &
frontend_pid=$!

echo "PlayTrack backend: http://${url_host}:8000"
if (( wildcard_host )); then
  echo "PlayTrack frontend (local): http://127.0.0.1:5173"
  if lan_ip="$(detect_lan_ip)"; then
    echo "PlayTrack frontend (network): http://${lan_ip}:5173"
  else
    echo "PlayTrack frontend (network): http://<this-machine-ip>:5173"
  fi
else
  echo "PlayTrack frontend: http://${url_host}:5173"
fi
if (( network_mode )); then
  echo "WARNING: Network mode has no authentication. Use only on a trusted local network."
fi
echo "Press Ctrl+C to stop both servers."

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

echo "One PlayTrack process stopped; shutting down the other."
cleanup
wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
exit 1
