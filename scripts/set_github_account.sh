#!/usr/bin/env bash
# Replace the placeholder account name in README.md and CITATION.cff.
#   bash scripts/set_github_account.sh your-github-username
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: bash scripts/set_github_account.sh <github-username>"; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/.."
sed -i.bak "s/REPLACE-WITH-YOUR-ACCOUNT/$1/g" README.md CITATION.cff && rm -f README.md.bak CITATION.cff.bak
grep -n "github.com/$1" README.md CITATION.cff
