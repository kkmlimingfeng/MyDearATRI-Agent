#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ "${CONDA_DEFAULT_ENV:-}" != "atri" ]] && command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
  if conda env list | awk '{print $1}' | grep -qx 'atri'; then
    conda activate atri
  fi
fi

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  else
    printf 'Python was not found. Activate the atri environment or set PYTHON_BIN.\n' >&2
    exit 1
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  printf 'npm was not found. Install Node.js and npm first.\n' >&2
  exit 1
fi
if [[ ! -d "$PROJECT_ROOT/web/node_modules" ]]; then
  printf 'Frontend dependencies are missing. Run: cd web && npm install\n' >&2
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import socket
import sys

conflicts = []
for host, port in (("127.0.0.1", 8765), ("0.0.0.0", 5173)):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            conflicts.append(port)

if conflicts:
    print("Port conflict: " + ", ".join(map(str, conflicts)) + " already in use.", file=sys.stderr)
    print("Stop the existing service(s) and run ./start.sh again.", file=sys.stderr)
    sys.exit(1)
PY
then
  exit 1
fi

backend_pid=''
frontend_pid=''
cleanup() {
  trap - INT TERM EXIT
  for process_id in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  for process_id in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$process_id" ]]; then
      wait "$process_id" 2>/dev/null || true
    fi
  done
}
trap cleanup INT TERM EXIT

"$PYTHON_BIN" "$PROJECT_ROOT/web_server.py" &
backend_pid=$!
(cd "$PROJECT_ROOT/web" && npm run dev -- --port 5173 --strictPort) &
frontend_pid=$!

printf 'ATRI backend: http://127.0.0.1:8765\n'
printf 'ATRI frontend: http://localhost:5173\n'
printf 'Press Ctrl+C to stop both services.\n'

if wait -n "$backend_pid" "$frontend_pid"; then
  exit 0
else
  exit_code=$?
  printf 'A service exited with status %s; stopping the other service.\n' "$exit_code" >&2
  exit "$exit_code"
fi
