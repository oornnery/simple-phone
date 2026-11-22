#!/usr/bin/env bash
# Static checks, metadata and unit tests (SIP only on localhost).
source "$(dirname "$0")/common.sh"
require_env
"$PYTHON" -m ruff check .
"$PYTHON" -m ruff format --check .
"$PYTHON" -m ty check
"$PYTHON" scripts/check_package.py --metadata
for script in scripts/*.sh; do
    bash -n "$script"
done
bash scripts/test.sh
