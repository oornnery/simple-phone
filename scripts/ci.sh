#!/usr/bin/env bash
# What .github/workflows/ci.yml runs, on this machine: run it before you push.
#   bash scripts/ci.sh            checks, unit, PJSUA2 and Asterisk tests
#   bash scripts/ci.sh --wheel    also build and check the wheel (before a release)
# The Asterisk tests need Docker; without it they are skipped, with a note.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
case "${1:-}" in
    ""|--wheel) ;;
    *) echo "Usage: bash scripts/ci.sh [--wheel]" >&2; exit 2 ;;
esac

bash scripts/check.sh
bash scripts/test.sh --native
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    trap 'bash scripts/asterisk.sh stop' EXIT
    bash scripts/asterisk.sh
    ASTERISK_HOST=127.0.0.1 .venv/bin/python -m unittest discover \
        -s tests -t tests -p 'test_asterisk.py'
else
    echo "Docker is not running: Asterisk tests skipped (CI runs them)." >&2
fi
if [[ "${1:-}" == --wheel ]]; then
    bash scripts/build.sh && .venv/bin/python scripts/check_package.py
fi
echo "ci.sh: all passed"
