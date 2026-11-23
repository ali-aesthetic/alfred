#!/usr/bin/env bash
# Copies the brain (Python source, persona, scripts) from the repo root into DEST:  bundle-brain.sh DEST
# Used by build.sh to put the brain inside Alfred.app. Allow-list only, so nothing personal can get in. Deletes nothing.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
mkdir -p "$DEST"
rsync -a \
  --exclude='/README.md' --exclude='/SIGNING.md' --exclude='/THIRD-PARTY.md' --exclude='/install.sh' \
  --include='/*.py' --include='/*.js' --include='/*.html' --include='/*.md' --include='/*.sh' --include='/*.command' \
  --include='/requirements.txt' --include='/config.example.json' --include='/console-icon.png' \
  --include='/persona/***' --include='/scripts/***' --include='/languages/***' --include='/brains/***' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*' \
  "$SRC/" "$DEST/"
