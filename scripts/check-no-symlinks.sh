#!/bin/bash
# No symlinks in git. Checks the index, so it works as a pre-commit hook (staged
# files) and in CI (the checkout). Sanctioned aliases: AGENTS.md -> CLAUDE.md
# and .markdownlint.yml -> the lint config.
set -euo pipefail
bad=$(git ls-files -s | awk '$1 == "120000" {print $4}' | grep -vxE 'AGENTS.md|.markdownlint.yml' || true)
[ -z "$bad" ] || { echo "symlinks in git: $bad" >&2; exit 1; }
