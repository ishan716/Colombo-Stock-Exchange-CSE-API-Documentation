#!/usr/bin/env bash
#
# Start the CSE portfolio dashboard and open it in a browser.
#
#   ./dashboard/run.sh                 # port 8000, opens a browser
#   ./dashboard/run.sh --port 8080
#   ./dashboard/run.sh --no-browser
#   ./dashboard/run.sh --reload        # restart on source edits
#
# Runs from any directory. Ctrl-C stops the server.

set -euo pipefail

PORT=8000
HOST=127.0.0.1
OPEN_BROWSER=1
RELOAD=0

usage() {
    sed -n '3,11p' "$0" | sed 's/^# \?//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--port)     PORT="${2:?--port needs a value}"; shift 2 ;;
        --host)        HOST="${2:?--host needs a value}"; shift 2 ;;
        -n|--no-browser) OPEN_BROWSER=0; shift ;;
        -r|--reload)   RELOAD=1; shift ;;
        -h|--help)     usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
done

case "$PORT" in
    ''|*[!0-9]*) echo "--port must be a number, got '$PORT'" >&2; exit 1 ;;
esac

# Repo root, resolved from this script rather than the caller's cwd, because
# uvicorn must import `dashboard.server.main` as a package.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
URL="http://$HOST:$PORT"

say() { printf '  %s\n' "$1"; }

# --- already running? -------------------------------------------------------
# If something answers our health route on this port, it is this dashboard --
# just open it instead of failing on a port clash.
if curl -fsS -m 2 "$URL/api/health" >/dev/null 2>&1; then
    say "already running at $URL"
    if [ "$OPEN_BROWSER" = 1 ]; then
        for o in xdg-open open; do
            if command -v "$o" >/dev/null 2>&1; then
                "$o" "$URL" >/dev/null 2>&1 && break
            fi
        done
    fi
    exit 0
fi

# Something else holds the port.
if command -v python3 >/dev/null 2>&1 && python3 - "$HOST" "$PORT" <<'PY' 2>/dev/null
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex((host, port)) == 0 else 1)
PY
then
    echo "port $PORT on $HOST is in use by something that is not this dashboard." >&2
    echo "try: $0 --port $((PORT + 1))" >&2
    exit 1
fi

# --- environment ------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
    say "creating virtualenv at .venv"
    python3 -m venv "$VENV"
fi
PY_BIN="$VENV/bin/python"

if ! "$PY_BIN" -c 'import fastapi, uvicorn, httpx, websocket' >/dev/null 2>&1; then
    say "installing dependencies"
    "$PY_BIN" -m pip install --quiet --upgrade pip
    "$PY_BIN" -m pip install --quiet -r "$ROOT/dashboard/requirements.txt"
fi

if [ ! -f "$ROOT/dashboard/holdings.json" ]; then
    say "no holdings.json yet -- starting with an empty portfolio"
    say "  cp dashboard/holdings.sample.json dashboard/holdings.json"
fi

# --- start ------------------------------------------------------------------
UVICORN_ARGS=(-m uvicorn dashboard.server.main:app --host "$HOST" --port "$PORT")
[ "$RELOAD" = 1 ] && UVICORN_ARGS+=(--reload)

say "starting server on $URL"
"$PY_BIN" "${UVICORN_ARGS[@]}" &
SERVER_PID=$!

cleanup() {
    trap - INT TERM EXIT
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup INT TERM EXIT

# --- wait for readiness, then open -----------------------------------------
# Opening before the server answers would just show a connection error.
ready=0
for _ in $(seq 1 60); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "server exited during startup -- see the output above" >&2
        wait "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
    if curl -fsS -m 2 "$URL/api/health" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.5
done

if [ "$ready" = 1 ]; then
    if [ "$OPEN_BROWSER" = 1 ]; then
        opened=0
        for o in xdg-open open; do
            if command -v "$o" >/dev/null 2>&1; then
                "$o" "$URL" >/dev/null 2>&1 && opened=1 && break
            fi
        done
        [ "$opened" = 1 ] || say "open $URL in your browser"
    else
        say "ready at $URL"
    fi
else
    say "server did not answer /api/health in 30s; leaving it running"
    say "try $URL yourself"
fi

say "Ctrl-C to stop"
wait "$SERVER_PID"
