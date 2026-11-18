#!/usr/bin/env bash
# Start the Flame spectrometer interface on macOS/Linux:  ./start.sh  [--mock]
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: creating Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
