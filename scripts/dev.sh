#!/usr/bin/env bash
# Development stack for ContractExtraction: one command for Docker services and the local processes.
#
#   scripts/dev.sh [up] [--ollama docker] [--workers N]   start everything in the foreground; Ctrl-C stops the app processes
#   scripts/dev.sh status                                 check every service (exit 1 if one fails)
#   scripts/dev.sh smoke [pytest args]                    end-to-end smoke test against the running stack
#   scripts/dev.sh test                                   every offline test suite (backend, gateway, frontend)
#   scripts/dev.sh down                                   stop the Docker services (data is kept)
#   scripts/dev.sh reset [--yes]                          wipe the database, vectors and stored files, then start Docker again
#
# Ports follow each part's own settings. To move one, export the variable the part reads (real environment variables
# override every config file), so this script and the services agree: API__PORT, GATEWAY__PORT.
# Runs in bash 3.2+ on macOS, Linux, and Windows in Git Bash or WSL. Git Bash has no POSIX signals for Windows programs,
# so there the processes are stopped with taskkill (see stop_all).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker/docker-compose.yml"
DEV_DIR="$ROOT/.dev"
LOG_DIR="$DEV_DIR/logs"

API_PORT="${API__PORT:-8000}"
GATEWAY_PORT="${GATEWAY__PORT:-8080}"
FRONTEND_PORT=5173   # fixed in frontend/vite.config.ts (strictPort)
API_URL="http://127.0.0.1:$API_PORT"
GATEWAY_URL="http://127.0.0.1:$GATEWAY_PORT"
FRONTEND_URL="http://localhost:$FRONTEND_PORT"   # Vite may listen on ::1 only

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) WINDOWS=1; VENV_BIN=Scripts; EXE=.exe ;;   # Git Bash: Windows virtualenv layout
  *) WINDOWS=0; VENV_BIN=bin; EXE="" ;;
esac

# The installed entry points, not `uv run` / `npm run`: those wrappers forward signals to their child, and the worker
# treats a second signal as "exit now" instead of "cancel the current run at its next field".
CE="$ROOT/backend/.venv/$VENV_BIN/contract-extraction$EXE"
GW="$ROOT/gateway/.venv/$VENV_BIN/contract-gateway$EXE"
BACKEND_PY="$ROOT/backend/.venv/$VENV_BIN/python$EXE"
VITE_JS="$ROOT/frontend/node_modules/vite/bin/vite.js"   # run with node: the same on every OS
PID_FILE="$DEV_DIR/pids"

READY_TIMEOUT=60   # seconds for every process to answer
STOP_TIMEOUT=15    # seconds before a process that ignores SIGTERM is killed

if [ -t 1 ]; then
  BOLD=$'\033[1m' RED=$'\033[31m' YELLOW=$'\033[33m' GREEN=$'\033[32m' RESET=$'\033[0m'
else
  BOLD="" RED="" YELLOW="" GREEN="" RESET=""
fi

info() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
line() { if [ "$1" = ok ]; then printf '  %sok  %s %s\n' "$GREEN" "$RESET" "$2"; else printf '  %sFAIL%s %s\n' "$RED" "$RESET" "$2"; fi; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
http_ok() { curl -fsS -o /dev/null --max-time 3 "$1" 2>/dev/null; }

need() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' is not installed or not on PATH"
  done
}

require_docker() {
  need docker
  docker info >/dev/null 2>&1 || die "Docker isn't running, or this user can't reach it (start Docker Desktop; on Linux, check the docker group)"
}

require_venvs() {
  [ -x "$CE" ] && [ -x "$GW" ] || die "Python environments are missing; run 'scripts/dev.sh' (up) once, or 'uv sync' in backend/ and gateway/"
}

# Same environment for both directions: when a port is moved with an env var, point the next hop at it as well.
export_hops() {
  if [ -n "${API__PORT:-}" ]; then export UPSTREAM__URL="$API_URL"; fi
  if [ -n "${GATEWAY__PORT:-}" ]; then export VITE_GATEWAY_URL="$GATEWAY_URL"; fi
  export PYTHONUNBUFFERED=1
  export PYTHONUTF8=1   # Windows: UTF-8 output through the pipe instead of the console code page
}

install_deps() {
  need uv npm
  info "Python dependencies (uv sync --locked)"
  (cd "$ROOT/backend" && uv sync --locked --quiet)
  (cd "$ROOT/gateway" && uv sync --locked --quiet)
  # npm ci deletes node_modules first, so only run it when the lockfile changed since the last install.
  if [ ! -f "$ROOT/frontend/node_modules/.package-lock.json" ] \
     || [ "$ROOT/frontend/package-lock.json" -nt "$ROOT/frontend/node_modules/.package-lock.json" ]; then
    info "Frontend dependencies (npm ci)"
    (cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
  fi
}

# A port is taken when something accepts a connection on it (curl exit 7 = nothing listening). Works without lsof,
# which Git Bash and minimal Linux installs lack; lsof only adds the owner's name when it's there.
port_in_use() {
  local code=0
  curl -s -o /dev/null --max-time 2 "http://localhost:$1/" || code=$?
  [ "$code" != 7 ] || return 1
  [ "$code" != 0 ] || return 0
  # localhost may have resolved to one address family only: try IPv4 explicitly before calling the port free.
  code=0
  curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/" || code=$?
  [ "$code" != 7 ]
}

check_ports_free() {
  local port owner busy=0
  for port in "$API_PORT" "$GATEWAY_PORT" "$FRONTEND_PORT"; do
    if port_in_use "$port"; then
      owner=""
      if command -v lsof >/dev/null 2>&1; then
        owner="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR > 1 {print " by " $1 " (pid " $2 ")"; exit}' || true)"
      fi
      printf '%serror:%s port %s is already in use%s\n' "$RED" "$RESET" "$port" "$owner" >&2
      busy=1
    fi
  done
  [ "$busy" = 0 ] || die "free the port(s) above (is another dev stack running? 'scripts/dev.sh status'), or move the API / gateway with API__PORT / GATEWAY__PORT"
}

# ---------------------------------------------------------------------------------------------------------------- up

NAMES=()
PIDS=()
STOPPING=0

# start NAME COLOUR DIR CMD...: runs CMD in DIR, in its own process group (set -m), so the terminal's Ctrl-C reaches only
# this script, which then sends exactly one SIGTERM. Output is prefixed on the terminal and copied to .dev/logs/NAME.log.
# The prefixing awk ignores SIGINT, so it keeps reading while the process shuts down.
start() {
  local name="$1" colour="$2" dir="$3"
  shift 3
  local log="$LOG_DIR/$name.log" prefix
  prefix="$(printf '\033[%sm%-8s|\033[0m ' "$colour" "$name")"
  [ -t 1 ] || prefix="$(printf '%-8s| ' "$name")"
  : >"$log"
  set -m   # only while forking: foreground commands (sleep, curl) stay in this script's group
  (cd "$dir" && exec "$@") \
    > >(trap '' INT; exec awk -v p="$prefix" -v out="$log" '{ print p $0; fflush(); print $0 >> out; fflush(out) }') 2>&1 &
  set +m
  NAMES+=("$name")
  PIDS+=("$!")
  echo "$name $!" >>"$PID_FILE"
}

# Terminate a process and its children for good: the process group on Unix, the process tree on Windows.
kill_hard() {
  if [ "$WINDOWS" = 1 ]; then
    local winpid
    winpid="$(cat "/proc/$1/winpid" 2>/dev/null || echo "$1")"
    MSYS_NO_PATHCONV=1 taskkill /PID "$winpid" /T /F >/dev/null 2>&1 || true
  else
    kill -KILL -- "-$1" 2>/dev/null || true
  fi
}

stop_all() {
  [ "$STOPPING" = 0 ] || return 0
  STOPPING=1
  [ "${#PIDS[@]}" -gt 0 ] || return 0
  local i pid waited=0 alive
  info "Stopping app processes (Docker services keep running; 'scripts/dev.sh down' stops them)"
  rm -f "$PID_FILE"
  if [ "$WINDOWS" = 1 ]; then
    # No SIGTERM for Windows programs: `kill` would end the process at once and leave its children running.
    # A run the worker was executing is marked failed by the next worker after WORKER__STALE_AFTER_SECONDS (120 s).
    for pid in "${PIDS[@]}"; do kill_hard "$pid"; done
    wait 2>/dev/null || true
    return 0
  fi
  for pid in "${PIDS[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  while [ "$waited" -lt $((STOP_TIMEOUT * 10)) ]; do
    alive=0
    for pid in "${PIDS[@]}"; do if kill -0 "$pid" 2>/dev/null; then alive=1; fi; done
    [ "$alive" = 1 ] || break
    sleep 0.1
    waited=$((waited + 1))
  done
  for i in "${!PIDS[@]}"; do
    pid="${PIDS[$i]}"
    if kill -0 "$pid" 2>/dev/null; then warn "${NAMES[$i]} ignored SIGTERM for ${STOP_TIMEOUT}s; killing it"; fi
    kill_hard "$pid"   # the whole group, so helpers such as esbuild never outlive their parent
  done
  wait 2>/dev/null || true
}

# The first process that has exited, as "index", or nothing.
first_exited() {
  local i
  for i in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then echo "$i"; return; fi
  done
}

fail_exited() {
  local i="$1" name="${NAMES[$1]}" code=0
  wait "${PIDS[$i]}" 2>/dev/null || code=$?
  printf '%serror:%s %s exited (status %s); last lines of .dev/logs/%s.log:\n' "$RED" "$RESET" "$name" "$code" "$name" >&2
  tail -n 15 "$LOG_DIR/$name.log" >&2 || true
  exit 1
}

wait_ready() {
  local name="$1" url="$2" waited=0 i
  until http_ok "$url"; do
    i="$(first_exited)"
    [ -z "$i" ] || fail_exited "$i"
    if [ "$waited" -ge "$READY_TIMEOUT" ]; then
      printf '%serror:%s %s did not answer %s within %ss; last lines of .dev/logs/%s.log:\n' \
        "$RED" "$RESET" "$name" "$url" "$READY_TIMEOUT" "$name" >&2
      tail -n 15 "$LOG_DIR/$name.log" >&2 || true
      exit 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
}

cmd_up() {
  local ollama="native" workers=1 n
  while [ $# -gt 0 ]; do
    case "$1" in
      --ollama) ollama="${2:-}"; shift 2 ;;
      --workers) workers="${2:-}"; shift 2 ;;
      *) die "unknown option for up: $1 (see the top of scripts/dev.sh)" ;;
    esac
  done
  case "$ollama" in native|docker) ;; *) die "--ollama takes 'native' or 'docker'" ;; esac
  case "$workers" in ''|*[!0-9]*|0) die "--workers takes a number of at least 1" ;; esac

  require_docker
  need curl awk node
  check_ports_free
  install_deps
  export_hops

  info "Docker services"
  if [ "$ollama" = docker ]; then
    compose --profile ollama up -d --build --wait
  else
    compose up -d --build --wait
  fi

  info "Service check (contract-extraction check)"
  if ! (cd "$ROOT/backend" && "$CE" check); then
    warn "the check failed. The UI, configuration and ground truth still work, but runs need the models above."
    warn "native Ollama: open Ollama.app, then 'ollama pull nomic-embed-text' and 'ollama pull llama3.1:8b'"
  fi
  if [ "$ollama" = docker ] && ! (cd "$ROOT/backend" && "$CE" providers) | grep -q '^ollama-local .*:11435'; then
    warn "Docker Ollama listens on :11435, but the ollama-local provider points elsewhere. To use it:"
    warn "  (cd backend && uv run contract-extraction providers set ollama-local --base-url http://localhost:11435)"
  fi

  mkdir -p "$LOG_DIR"
  : >"$PID_FILE"
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap stop_all EXIT

  info "Starting the API, ${workers} worker(s), the gateway and the frontend (logs in .dev/logs/)"
  start api 36 "$ROOT/backend" "$CE" api
  n=1
  while [ "$n" -le "$workers" ]; do
    start "worker$n" 35 "$ROOT/backend" "$CE" worker
    n=$((n + 1))
  done
  start gateway 33 "$ROOT/gateway" "$GW"
  start frontend 32 "$ROOT/frontend" node "$VITE_JS" --clearScreen false

  wait_ready api "$API_URL/api/v1/health"
  wait_ready gateway "$GATEWAY_URL/health"
  wait_ready frontend "$FRONTEND_URL/"

  printf '\n%sReady.%s\n' "$GREEN$BOLD" "$RESET"
  printf '  UI        %s\n' "$FRONTEND_URL"
  printf '  API docs  %s/api/v1/docs   (through the gateway)\n' "$GATEWAY_URL"
  printf '  Health    %s/health\n' "$GATEWAY_URL"
  printf '  Logs      .dev/logs/\n'
  printf 'Ctrl-C stops the app processes. The worker does not reload: restart after changing pipeline code.\n\n'

  local i
  while true; do
    i="$(first_exited)"
    [ -z "$i" ] || fail_exited "$i"
    sleep 1
  done
}

# ------------------------------------------------------------------------------------------------------------ status

# Workers on this machine: every one (also those started by hand) where pgrep exists, otherwise those started by up.
count_workers() {
  if command -v pgrep >/dev/null 2>&1; then
    (pgrep -f "$VENV_BIN/contract-extraction$EXE worker" || true) | wc -l | tr -d ' '
    return
  fi
  local name pid n=0
  if [ -f "$PID_FILE" ]; then
    while read -r name pid; do
      case "$name" in worker*) if kill -0 "$pid" 2>/dev/null; then n=$((n + 1)); fi ;; esac
    done <"$PID_FILE"
  fi
  echo "$n"
}

cmd_status() {
  need curl
  require_venvs
  local failed=0 count
  info "Configuration and services (contract-extraction check)"
  (cd "$ROOT/backend" && "$CE" check) || failed=1

  info "App processes"
  if http_ok "$API_URL/api/v1/health"; then line ok "api: $API_URL"; else line fail "api: $API_URL/api/v1/health"; failed=1; fi
  if http_ok "$GATEWAY_URL/health"; then line ok "gateway: $GATEWAY_URL"; else line fail "gateway: $GATEWAY_URL/health"; failed=1; fi
  count="$(count_workers)"
  if [ "$count" -gt 0 ]; then line ok "worker: $count running"; else line fail "worker: none running"; failed=1; fi
  if http_ok "$FRONTEND_URL/"; then line ok "frontend: $FRONTEND_URL"; else line fail "frontend: $FRONTEND_URL"; failed=1; fi
  if http_ok "$FRONTEND_URL/api/v1/health"; then
    line ok "frontend → gateway proxy: $FRONTEND_URL/api/v1/health"
  else
    line fail "frontend → gateway proxy: $FRONTEND_URL/api/v1/health"; failed=1
  fi
  if [ "$failed" = 0 ]; then echo "OK"; else echo "FAIL"; fi
  return "$failed"
}

# ----------------------------------------------------------------------------------------------------- smoke / test

cmd_smoke() {
  need uv
  (cd "$ROOT/backend" && CE_SMOKE=1 CE_GATEWAY_URL="$GATEWAY_URL" CE_FRONTEND_URL="$FRONTEND_URL" \
    uv run pytest -m smoke -s "$@")
}

cmd_test() {
  require_docker
  install_deps
  info "Docker services (the backend's database tests need Postgres)"
  compose up -d --build --wait
  info "backend: pytest"
  (cd "$ROOT/backend" && uv run pytest)
  info "gateway: pytest"
  (cd "$ROOT/gateway" && uv run pytest)
  info "frontend: test, typecheck, lint"
  (cd "$ROOT/frontend" && npm test && npm run typecheck && npm run lint)
  printf '%sAll suites passed.%s\n' "$GREEN" "$RESET"
}

# ------------------------------------------------------------------------------------------------------- down / reset

cmd_down() {
  require_docker
  compose --profile ollama down
}

cmd_reset() {
  local yes=0 storage answer
  case "${1:-}" in --yes|-y) yes=1 ;; "") ;; *) die "unknown option for reset: $1" ;; esac
  require_docker
  require_venvs
  # The storage root from the backend's settings (STORAGE__ROOT): document codes restart at DOC001 with a new database.
  storage="$(cd "$ROOT/backend" && "$BACKEND_PY" -c 'from contract_extraction.core.settings import load_settings; print(load_settings().storage_root)')"
  if [ "$WINDOWS" = 1 ]; then storage="$(cygpath -u "$storage")"; fi   # C:\... → /c/...
  if [ "$yes" = 0 ]; then
    printf 'This deletes the Postgres and Qdrant volumes (every document, run, label and config edit)\n'
    printf 'and empties the storage folder %s.\n' "$storage"
    read -r -p "Continue? [y/N] " answer
    case "$answer" in y|Y|yes) ;; *) echo "Cancelled."; exit 1 ;; esac
  fi
  info "Removing the Postgres and Qdrant volumes (Docker Ollama's models are kept)"
  compose --profile ollama down
  docker volume rm -f contract-extraction_postgres-data contract-extraction_qdrant-data >/dev/null
  if [ -d "$storage" ]; then
    info "Emptying $storage"
    find "$storage" -mindepth 1 -delete
  fi
  info "Starting Docker services with a fresh database"
  compose up -d --build --wait
  info "Done. Start the app processes with scripts/dev.sh"
}

# -------------------------------------------------------------------------------------------------------------- main

command="${1:-up}"
[ $# -eq 0 ] || shift
case "$command" in
  up) cmd_up "$@" ;;
  status) cmd_status ;;
  smoke) cmd_smoke "$@" ;;
  test) cmd_test ;;
  down) cmd_down ;;
  reset) cmd_reset "$@" ;;
  -h|--help|help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
  -*) cmd_up "$command" "$@" ;;
  *) die "unknown command '$command' (up, status, smoke, test, down, reset)" ;;
esac
