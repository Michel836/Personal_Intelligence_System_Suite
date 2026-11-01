#!/usr/bin/env bash
# Desktop launcher helper for 36TB Intelligence.
# Installed (with absolute paths substituted) as ~/.local/bin/36tb-launch.
#
#   ../../.local/bin/36tb-launch lite|smart|full
#   ../../.local/bin/36tb-launch --stop lite|smart|full
set -euo pipefail

ACTION="${1:-full}"
PROFILE="$ACTION"
STOP=0
if [ "$ACTION" = "--stop" ]; then
    STOP=1
    PROFILE="${2:-full}"
fi

ROOT="@ROOT@"
PY="@PY@"
HOST="127.0.0.1"

case "$PROFILE" in
    lite)  PREFERRED_PORT=8510 ;;
    smart) PREFERRED_PORT=8504 ;;
    full)  PREFERRED_PORT=8501 ;;
    *) echo "unknown profile: $PROFILE (expected lite|smart|full)" >&2; exit 2 ;;
esac

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pis"
LOG="$STATE_DIR/desktop-${PROFILE}.log"
PID_FILE="$STATE_DIR/desktop-${PROFILE}.pid"
mkdir -p "$STATE_DIR"
cd "$ROOT"

open_url() {
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 &
    elif command -v gio >/dev/null 2>&1; then
        gio open "$1" >/dev/null 2>&1 &
    fi
}

notify() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "36TB Intelligence" "$1" >/dev/null 2>&1 || true
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --title "36TB Intelligence" --passivepopup "$1" 8 >/dev/null 2>&1 || true
    fi
}

healthy() {
    curl -fsS --max-time 2 "http://$HOST:$1/_stcore/health" >/dev/null 2>&1
}

stop_profile() {
    local stopped=0 pid pids p
    if [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            # The wrapper starts the launcher under setsid: PID == PGID.
            kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
            stopped=1
        fi
        rm -f "$PID_FILE"
    fi
    # Fallback: stop the Streamlit app listening on the profile's port.
    pids="$(pgrep -f "src/ui/app.py --server.port $PREFERRED_PORT" 2>/dev/null || true)"
    for p in $pids; do
        kill "$p" 2>/dev/null && stopped=1 || true
    done
    if [ "$stopped" = 1 ]; then
        notify "Profil ${PROFILE^^} arrêté."
    else
        notify "Aucune instance ${PROFILE^^} en cours."
    fi
    exit 0
}

if [ "$STOP" = 1 ]; then
    stop_profile
fi

# Already running on the profile's preferred port: just open it.
if healthy "$PREFERRED_PORT"; then
    open_url "http://$HOST:$PREFERRED_PORT"
    exit 0
fi

# Pick a free port near the preferred one (tolerates another app on the port).
PORT="$("$PY" -c "from src.launcher import find_free_port; print(find_free_port('$HOST', $PREFERRED_PORT))")"
if [ -z "$PORT" ]; then
    notify "Aucun port libre pour le profil $PROFILE."
    exit 1
fi

setsid nohup "$PY" -m src.launcher --profile "$PROFILE" --port "$PORT" \
    >>"$LOG" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

# Wait for Streamlit, then open the browser once.
for _ in $(seq 1 120); do
    if healthy "$PORT"; then
        open_url "http://$HOST:$PORT"
        exit 0
    fi
    sleep 0.5
done

# Failure: do not leave a half-started server behind.
kill -- "-$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
notify "Le serveur $PROFILE n'a pas démarré. Journal : $LOG"
exit 1
