#!/usr/bin/env bash
# Launch Jupyter notebook for dazpy interactive work.
# Installs required packages if missing. Works in Git Bash on Windows.

set -euo pipefail

check_package() {
    python -c "import $1" 2>/dev/null
}

echo "==> Checking Python..."
if ! command -v python &>/dev/null; then
    echo "ERROR: Python not found. Install Python 3.9+ and ensure it is on PATH." >&2
    exit 1
fi
python --version

echo "==> Installing/verifying dazpy SDK (editable)..."
pip install -e . --quiet

echo "==> Checking for Jupyter..."
if ! check_package jupyter_server; then
    echo "    Installing notebook..."
    pip install notebook --quiet
else
    echo "    Jupyter already installed."
fi

NOTEBOOKS_DIR="$(dirname "$0")/notebooks"
if [ ! -d "$NOTEBOOKS_DIR" ]; then
    mkdir -p "$NOTEBOOKS_DIR"
    echo "==> Created notebooks/ directory."
fi

echo ""
echo "==> Starting Jupyter Notebook..."
echo "    DAZ Studio must be running with the DazScriptServer plugin active."
echo "    Default server: http://127.0.0.1:18811"
echo ""

jupyter notebook --notebook-dir="$NOTEBOOKS_DIR"
