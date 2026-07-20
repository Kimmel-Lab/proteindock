#!/usr/bin/env bash
# ProteinDock backend installer.
# Creates a Python 3.10+ virtualenv, installs dependencies, and stubs config.json
# from config.example.json. After install, run: python configure.py; ./run.sh
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
VENV_DIR="${REPO_DIR}/venv"

msg()  { printf "\033[1;32m[install]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[install]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[install]\033[0m %s\n" "$*" >&2; exit 1; }

# --- 1. Python check ---
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || die "python3 not found. Install Python 3.10+ and re-run."
PY_VER=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
msg "Using ${PYTHON} (${PY_VER})"
case "$PY_VER" in
  3.10|3.11|3.12) : ;;
  *) warn "Python ${PY_VER} is untested. Recommended: 3.10, 3.11, or 3.12." ;;
esac

# --- 2. Virtualenv ---
if [[ ! -d "$VENV_DIR" ]]; then
  msg "Creating virtualenv at ${VENV_DIR}"
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip

# --- 3. Python dependencies ---
msg "Installing Python dependencies (this can take a couple of minutes)"
pip install --quiet \
  "fastapi>=0.110" "uvicorn[standard]>=0.29" \
  "python-multipart" "pydantic>=2" \
  "biopython>=1.83" "numpy" "scipy" \
  "requests" "aiofiles"

# PyRosetta is deliberately NOT installed by this script.
# The RosettaCommons license requires each user to obtain PyRosetta directly.
# The install can finish without it; ProteinDock's UI will load and Mode 2
# rescoring endpoints work, but any full Mode 1 docking call will fail until
# PyRosetta is on the PYTHONPATH.
if ! python -c "import pyrosetta" 2>/dev/null; then
  warn "PyRosetta is not installed — this is intentional."
  warn "  ProteinDock does not redistribute Rosetta or PyRosetta; the RosettaCommons"
  warn "  license requires you to obtain them yourself:"
  warn "    Rosetta:    https://rosettacommons.org/software/download"
  warn "    PyRosetta:  https://www.pyrosetta.org/downloads"
  warn "  Once installed, install the PyRosetta wheel into this venv:"
  warn "    source ${VENV_DIR}/bin/activate && pip install /path/to/pyrosetta-*.whl"
fi

# --- 4. Stub config.json from example ---
if [[ ! -f "${REPO_DIR}/config.json" ]]; then
  cp "${REPO_DIR}/config.example.json" "${REPO_DIR}/config.json"
  msg "Wrote config.json (edit paths, or run: python configure.py)"
fi

msg "Install complete."
msg "Next steps:"
msg "  1. python configure.py    # interactive path setup"
msg "  2. ./run.sh               # start the backend"
