#!/bin/bash
# Push main to GitHub using the token in ~/.config/pelobrossss/github_token.
set -e
cd "$(dirname "$0")/.."
f="$HOME/.config/pelobrossss/github_token"
if [ ! -s "$f" ]; then echo "No GitHub token at $f; push skipped (push from GitHub Desktop instead)."; exit 2; fi
git -c credential.helper= -c "credential.helper=$PWD/tools/git-credential-token.sh" push origin main
