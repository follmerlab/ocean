#!/usr/bin/env bash
# Start the Flame spectrometer interface on macOS/Linux:  bash start.sh  [--mock]
# The first run builds a private Python environment in .venv (needs internet, ~2 min).
set -e
cd "$(dirname "$0")"

env_ok() { [ -x .venv/bin/python ] && .venv/bin/python -c "import flask, numpy, seabreeze" >/dev/null 2>&1; }

if ! env_ok; then
  if [ -d .venv ]; then
    echo "The Python environment is incomplete; rebuilding it..."
    rm -rf .venv
  fi
  # The spectrometer library (seabreeze) has packages for Python 3.11-3.14, not yet 3.15,
  # and the Mac's built-in python3 (3.9) is too old.
  PY=""
  for c in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(not (3, 11) <= sys.version_info[:2] <= (3, 14))' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo
    echo "  Python 3.14 (or 3.11-3.13) is needed and was not found."
    echo "  Python 3.15 is too new: the spectrometer library does not support it yet."
    echo
    echo "  Mac: install Python 3.14 from https://www.python.org/downloads/macos/"
    echo "       (a 3.14.x \"macOS 64-bit universal2 installer\"), or: brew install python@3.14"
    echo "  Then run this again."
    echo
    exit 1
  fi
  echo "First run: setting up Python with $PY ($("$PY" --version)); needs internet, about 2 minutes..."
  "$PY" -m venv .venv &&
    .venv/bin/python -m pip install --upgrade pip --quiet &&
    .venv/bin/python -m pip install -r requirements.txt ||
    { echo; echo "  Setup failed; see the messages above. Check the internet and run again (it resumes)."; exit 1; }
  echo "Setup finished."
fi

[ "$1" = "--setup-only" ] && exit 0
exec .venv/bin/python app.py "$@"
