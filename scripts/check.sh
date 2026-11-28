#!/usr/bin/env bash
# Static checks, metadata and unit tests (SIP only on localhost).
source "$(dirname "$0")/common.sh"
require_env
"$PYTHON" -m ruff check .
"$PYTHON" -m ruff format --check .
"$PYTHON" -m ty check
"$PYTHON" -m ty check --python-platform win32  # Windows-only stdlib gaps
"$PYTHON" scripts/check_package.py --metadata
for script in scripts/*.sh; do
    bash -n "$script"
done
bash scripts/test.sh
# A Windows pipe is cp1252: the command must still print (and exit 0).
PYTHONIOENCODING=cp1252 "$PYTHON" -m unittest discover -s tests -t tests -p test_cli.py
