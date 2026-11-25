#!/usr/bin/env bash
# Tests for python-relevant.sh: which PR file lists skip the Python suite.
set -uo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../python-relevant.sh"

pass=0
fail=0
check() { # desc expected files...
  local desc=$1 want=$2 got
  shift 2
  got=$(printf '%s\n' "$@" | "$SCRIPT")
  if [ "$want" = "$got" ]; then echo "ok   - $desc"; pass=$((pass + 1))
  else echo "FAIL - $desc (expected '$want', got '$got')"; fail=$((fail + 1)); fi
}

check "Next.js only" false next-app/src/app/page.tsx next-app/package.json
check "docs and Markdown only" false docs/inkorg.md README.md TESTING.md
check "Markdown read by the tests" true app/tests/membership_lifecycle.md
check "Python file" true next-app/src/app/page.tsx app/utils/database.py
check "this workflow" true .github/workflows/python_tests.yml
check "nginx" true nginx/nginx.main
check "Dockerfile outside next-app" true .docker/next-app
check "empty list" false ""

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
