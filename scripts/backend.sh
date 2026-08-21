#!/usr/bin/env bash
# Start/stop/status control for the FastAPI backend, run natively on this
# machine (no Docker -- Docker can't reach this box's Isaac Sim install,
# which kit_render_worker.py and /validate-usd need to shell out to).
#
# Usage:
#   scripts/backend.sh start    # installs uv/deps if missing, then runs in background
#   scripts/backend.sh stop
#   scripts/backend.sh restart
#   scripts/backend.sh status
#   scripts/backend.sh logs     # tail -f the backend's log file
#
# For interactive development with auto-reload on file changes, use
# `make backend-dev` instead (runs in the foreground, Ctrl-C to stop).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$REPO_ROOT/backend"
PID_FILE="$BACKEND_DIR/.backend.pid"
LOG_FILE="$BACKEND_DIR/backend.log"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

export PATH="$HOME/.local/bin:$PATH"

ensure_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found -- installing to \$HOME/.local/bin..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
}

ensure_env_file() {
  if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "Created backend/.env from .env.example -- edit it and set a real" >&2
    echo "OPENROUTER_API_KEY before using chat / Generate Fix Report (other" >&2
    echo "endpoints like /generate-usd, /render, /validate-usd don't need it)." >&2
  fi
}

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
  if is_running; then
    echo "Backend already running (PID $(cat "$PID_FILE"))."
    return 0
  fi
  ensure_uv
  ensure_env_file
  cd "$BACKEND_DIR"
  echo "Syncing dependencies (uv sync --extra usd)..."
  uv sync --extra usd
  echo "Starting backend on $HOST:$PORT (log: $LOG_FILE)..."
  nohup uv run --extra usd uvicorn main:app --host "$HOST" --port "$PORT" --app-dir src \
    > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 2
  if is_running; then
    echo "Backend started (PID $(cat "$PID_FILE")). Tail logs: $0 logs"
  else
    echo "Backend failed to start -- check $LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop() {
  if is_running; then
    kill "$(cat "$PID_FILE")"
    rm -f "$PID_FILE"
    echo "Backend stopped."
  else
    echo "Backend is not running."
    rm -f "$PID_FILE"
  fi
}

status() {
  if is_running; then
    echo "Backend running (PID $(cat "$PID_FILE")) on port $PORT."
  else
    echo "Backend is not running."
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  logs) tail -f "$LOG_FILE" ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
