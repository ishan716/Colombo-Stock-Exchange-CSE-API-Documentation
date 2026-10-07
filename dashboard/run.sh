#!/usr/bin/env bash
#
# Start the CSE portfolio dashboard and open it in a browser.
#
#   ./dashboard/run.sh                 # port 8000, opens a browser
#   ./dashboard/run.sh --port 8080
#   ./dashboard/run.sh --no-browser
#   ./dashboard/run.sh --reload        # restart on source edits
#
# Linux, macOS, WSL and Git Bash. For PowerShell or cmd.exe use run.ps1.
# Runs from any directory. Ctrl-C stops the server.

set -euo pipefail

PORT=8000
HOST=127.0.0.1
OPEN_BROWSER=1
RELOAD=0

usage() {
    sed -n '3,12p' "$0" | sed 's/^# \?//'
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

# --- platform shims ---------------------------------------------------------

# A system python to build the venv with. Windows generally has `python` or the
# `py` launcher rather than `python3`.
PYTHON=()
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 \
       && "$c" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; then
        PYTHON=("$c")
        break
    fi
done
if [ ${#PYTHON[@]} -eq 0 ] && command -v py >/dev/null 2>&1 \
   && py -3 -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; then
    PYTHON=(py -3)
fi
if [ ${#PYTHON[@]} -eq 0 ]; then
    echo "no Python 3 on PATH (tried python3, python, py -3)" >&2
    exit 1
fi

# venv layout differs by platform: bin/python on POSIX, Scripts/python.exe on
# Windows (Python's "nt" install scheme).
venv_python() {
    if [ -x "$VENV/bin/python" ]; then
        printf '%s\n' "$VENV/bin/python"
    elif [ -x "$VENV/Scripts/python.exe" ]; then
        printf '%s\n' "$VENV/Scripts/python.exe"
    else
        return 1
    fi
}

open_url() {
    # xdg-open before open: on some Linux distros `open` is openvt, not a browser.
    if command -v wslview >/dev/null 2>&1; then
        wslview "$1" >/dev/null 2>&1 && return 0
    fi
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 && return 0
    fi
    if command -v open >/dev/null 2>&1; then
        open "$1" >/dev/null 2>&1 && return 0
    fi
    # explorer.exe reaches the Windows browser from WSL and Git Bash, but exits
    # non-zero even when it succeeds, so its status is not checked.
    if command -v explorer.exe >/dev/null 2>&1; then
        explorer.exe "$1" >/dev/null 2>&1 || true
        return 0
    fi
    if command -v cmd >/dev/null 2>&1; then
        cmd //c start "" "$1" >/dev/null 2>&1 && return 0
    fi
    return 1
}

port_is_open() {
    "${PYTHON[@]}" - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.settimeout(1)
code = s.connect_ex((sys.argv[1], int(sys.argv[2])))
s.close()
sys.exit(0 if code == 0 else 1)
PY
}

health_ok() {
    curl -fsS -m 2 "$URL/api/health" >/dev/null 2>&1
}

# --- already running? -------------------------------------------------------
# If something answers our health route on this port, it is this dashboard --
# just open it instead of failing on a port clash.
if health_ok; then
    say "already running at $URL"
    if [ "$OPEN_BROWSER" = 1 ]; then
        open_url "$URL" || say "open $URL in your browser"
    fi
    exit 0
fi

if port_is_open; then
    echo "port $PORT on $HOST is in use by something that is not this dashboard." >&2
    echo "try: $0 --port $((PORT + 1))" >&2
    exit 1
fi

# --- environment ------------------------------------------------------------
if ! venv_python >/dev/null; then
    say "creating virtualenv at .venv"
    "${PYTHON[@]}" -m venv "$VENV"
fi
PY_BIN="$(venv_python)" || {
    echo "virtualenv at $VENV has no python -- delete it and re-run" >&2
    exit 1
}

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
tries=0
while [ "$tries" -lt 60 ]; do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "server exited during startup -- see the output above" >&2
        wait "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
    if health_ok; then
        ready=1
        break
    fi
    tries=$((tries + 1))
    sleep 0.5
done

if [ "$ready" = 1 ]; then
    if [ "$OPEN_BROWSER" = 1 ]; then
        open_url "$URL" || say "open $URL in your browser"
    else
        say "ready at $URL"
    fi
else
    say "server did not answer /api/health in 30s; leaving it running"
    say "try $URL yourself"
fi

say "Ctrl-C to stop"
wait "$SERVER_PID"
