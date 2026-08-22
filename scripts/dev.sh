#!/usr/bin/env bash
# Combined local dev launcher: backend (background, native, no Docker -- Docker
# can't reach this box's Isaac Sim install) + frontend (foreground, Vite).
#
# Usage: scripts/dev.sh
#
# The backend keeps running under scripts/backend.sh's own independent
# start/stop/status/logs lifecycle after this script exits -- Ctrl-C here only
# stops the frontend dev server, not the backend. Manage the backend directly
# with scripts/backend.sh {stop|status|logs|restart} when you're done.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
UI_DIR="$REPO_ROOT/ui"

"$SCRIPT_DIR/backend.sh" start

if [ ! -d "$UI_DIR/node_modules" ]; then
  echo "Installing frontend dependencies (npm install)..."
  (cd "$UI_DIR" && npm install)
fi

echo ""
echo "Backend running in the background -- manage it independently with:"
echo "  scripts/backend.sh {status|logs|stop|restart}"
echo ""
echo "Starting frontend dev server (Ctrl-C stops only this, not the backend)..."
cd "$UI_DIR"
exec npm run dev
