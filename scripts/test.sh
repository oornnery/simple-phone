#!/usr/bin/env bash
# --native opens loopback SIP/RTP sockets; --all also runs unit tests.
source "$(dirname "$0")/common.sh"
require_env
unit() {
    "$PYTHON" -m unittest discover -s tests -t tests -p 'test_*.py' -v
}
case "${1:-unit}" in
    unit) unit ;;
    --native) "$PYTHON" tests/native_checks.py -v ;;
    --all) unit && "$PYTHON" tests/native_checks.py -v ;;
    *) echo "Usage: bash scripts/test.sh [--native|--all]" >&2; exit 2 ;;
esac
