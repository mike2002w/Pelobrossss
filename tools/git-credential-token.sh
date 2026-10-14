#!/bin/bash
# git credential helper: answers with the GitHub token stored outside the repo.
# Used only by tools/push.sh. The token file is never printed anywhere else.
if [ "$1" = "get" ]; then
  f="$HOME/.config/pelobrossss/github_token"
  [ -s "$f" ] || exit 1
  echo "username=x-access-token"
  echo "password=$(tr -d '[:space:]' < "$f")"
fi
