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

stop_project_dev_servers() {
  local project_path="$PROJECT_ROOT/web"
  local pids=''
  local pid

  if command -v pgrep >/dev/null 2>&1; then
    pids="$(pgrep -f "vite.*$project_path|npm run dev.*$project_path" || true)"
  elif command -v ps >/dev/null 2>&1; then
    pids="$(ps -eo pid=,args= | awk -v path="$project_path" 'index($0, path) && ($0 ~ /vite/ || $0 ~ /npm run dev/) {print $1}' || true)"
  fi

  for pid in $pids; do
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    printf 'Stopping stale project frontend process %s.\n' "$pid" >&2
    kill -TERM "$pid" 2>/dev/null || true
  done
  [[ -z "$pids" ]] || sleep 1
  for pid in $pids; do
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      printf 'Force killing stale project frontend process %s.\n' "$pid" >&2
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

stop_project_dev_servers

# Free a port by terminating the processes that occupy it.
free_port() {
  local port="$1"
  local pids=''
  local attempt
  local pid
  local finder=''

  if command -v lsof >/dev/null 2>&1; then
    finder=lsof
  elif command -v fuser >/dev/null 2>&1; then
    finder=fuser
  elif command -v ss >/dev/null 2>&1; then
    finder=ss
  else
    printf 'Cannot inspect port %s: install lsof, fuser, or iproute2 (ss).\n' "$port" >&2
    return 1
  fi

  for attempt in 1 2 3; do
    case "$finder" in
      lsof) pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)" ;;
      fuser) pids="$(fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' || true)" ;;
      ss) pids="$(ss -ltnp 2>/dev/null | awk -v port="$port" '$4 ~ ":"port"$' \
        | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)" ;;
    esac
    pids="$(printf '%s\n' "$pids" | awk '/^[0-9]+$/ && !seen[$0]++')"
    if [[ -z "$pids" ]]; then
      if ! "$PYTHON_BIN" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("0.0.0.0", port))
    except OSError:
        sys.exit(1)
PY
      then
        if [[ "$finder" == ss ]]; then
          printf 'Port %s is occupied, but ss did not expose a PID. Cannot safely terminate it.\n' "$port" >&2
          return 1
        fi
        sleep 1
        continue
      fi
      return 0
    fi

    printf 'Port %s is in use by pid(s): %s. Terminating...\n' "$port" "$(tr '\n' ' ' <<<"$pids")" >&2
    while IFS= read -r pid; do
      [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
    done <<<"$pids"
    sleep 1
    while IFS= read -r pid; do
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'Force killing pid %s on port %s.\n' "$pid" "$port" >&2
        kill -KILL "$pid" 2>/dev/null || true
      fi
    done <<<"$pids"
    sleep 1
  done

  printf 'Could not release port %s after force-killing detected process(es).\n' "$port" >&2
  case "$finder" in
    lsof) lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true ;;
    fuser) fuser -v -n tcp "$port" >&2 || true ;;
    ss) ss -ltnp "sport = :$port" >&2 || true ;;
  esac
  return 1
}

free_port 8765
free_port 5173

# Verify the ports are actually free now; bail out if something still holds them.
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
    print("Port conflict: " + ", ".join(map(str, conflicts)) + " still in use after cleanup.", file=sys.stderr)
    print("Check the process details above, or run ./start.sh with permission to terminate it.", file=sys.stderr)
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
