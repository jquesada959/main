#!/usr/bin/env bash
# Wrapper to run sh_int_and_sh_mac.py using the project's virtualenv
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$HOME/.venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/sh_int_and_sh_mac.py"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/sh_int_and_sh_mac_${TIMESTAMP}.log"

if [ ! -x "$VENV_PY" ]; then
  echo "Warning: Python executable $VENV_PY not found or not executable. Falling back to system python3." >&2
  VENV_PY=$(command -v python3 || true)
  if [ -z "$VENV_PY" ]; then
    echo "No python3 available in PATH. Exiting." >&2
    exit 2
  fi
fi

echo "Running $PY_SCRIPT at $(date -u) (UTC). Log: $LOG_FILE"
"$VENV_PY" "$PY_SCRIPT" >>"$LOG_FILE" 2>&1 || rc=$?
exit ${rc:-0}
