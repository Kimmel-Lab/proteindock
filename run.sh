#!/usr/bin/env bash
# Launch the ProteinDock backend.
# Usage:  ./run.sh                 # default: 0.0.0.0:8000
#         ./run.sh 9000            # custom port
#         PORT=9000 HOST=127.0.0.1 ./run.sh
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
VENV_DIR="${REPO_DIR}/venv"

HOST="${HOST:-0.0.0.0}"
PORT="${1:-${PORT:-8000}}"

[[ -d "$VENV_DIR" ]] || { echo "venv missing — run ./install.sh first" >&2; exit 1; }
[[ -f "$REPO_DIR/config.json" ]] || { echo "config.json missing — run: python configure.py" >&2; exit 1; }

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

cd "$REPO_DIR"
echo "ProteinDock backend starting on http://${HOST}:${PORT}"
echo "  (paste this URL into the Settings dialog at https://proteindock.com)"
exec uvicorn backend.main:app --host "$HOST" --port "$PORT"
