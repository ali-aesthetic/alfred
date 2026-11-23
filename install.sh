#!/usr/bin/env bash
# Alfred installer for macOS (Apple Silicon). No Apple Developer account needed. Deletes nothing.
#
#   From a downloaded copy of this repo:   bash install.sh
#   One line (after the repo is public):    curl -fsSL https://raw.githubusercontent.com/<GH_USER>/alfred/main/install.sh | bash
#
# Home folder: $ALFRED_HOME  (default ~/Library/Application Support/Alfred). Set ALFRED_HOME to install somewhere else.
# Prefer a double-click app? Use Alfred.dmg from the Releases page instead; the app does all of this itself on first run.
set -euo pipefail

REPO="${ALFRED_REPO:-https://github.com/<GH_USER>/alfred.git}"
export ALFRED_HOME="${ALFRED_HOME:-$HOME/Library/Application Support/Alfred}"
HOME_DIR="$ALFRED_HOME"

say()  { printf "\n\033[1;33m▶ %s\033[0m\n" "$1"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

# ── 1. Check the Mac ─────────────────────────────────────────────────
say "Checking your Mac"
[ "$(uname -s)" = "Darwin" ] || die "Alfred is Mac only."
[ "$(uname -m)" = "arm64" ]  || die "Needs an Apple Silicon Mac (M1 or later)."
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 14 ] || die "Needs macOS 14 or newer."
xcode-select -p >/dev/null 2>&1 || { xcode-select --install || true; die "Install the Command Line Tools (a window just opened), then run this again."; }
FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
[ "${FREE_GB:-0}" -ge 6 ] || die "Need about 6 GB free disk space."

# ── 2. Find the code (this folder, or a fresh clone) ─────────────────
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/alfred.py" ]; then
  SRC="$SELF_DIR"
else
  say "Downloading Alfred's code"
  SRC="$(mktemp -d "${TMPDIR:-/tmp}/alfred-src.XXXXXX")"
  git clone --depth 1 "$REPO" "$SRC"
fi

# ── 3. Put the brain in your home folder ─────────────────────────────
say "Installing into $HOME_DIR"
mkdir -p "$HOME_DIR/data" "$HOME_DIR/bin"
bash "$SRC/mac-app/bundle-brain.sh" "$HOME_DIR"
cp "$SRC"/scripts/* "$HOME_DIR/bin/" && chmod +x "$HOME_DIR"/bin/*
[ -f "$HOME_DIR/config.json" ] || cp "$HOME_DIR/config.example.json" "$HOME_DIR/config.json"   # never overwrites your settings

# ── 4. Private Python (uv) + packages ────────────────────────────────
say "Setting up Python (private; your system Python is untouched)"
export UV_PYTHON_INSTALL_DIR="$HOME_DIR/python" UV_CACHE_DIR="$HOME_DIR/.uv-cache" UV_LINK_MODE=copy
if [ ! -x "$HOME_DIR/bin/uv" ]; then
  UV_INSTALL_DIR="$HOME_DIR/bin" INSTALLER_NO_MODIFY_PATH=1 sh -c "$(curl -LsSf https://astral.sh/uv/install.sh)"
fi
export PATH="$HOME_DIR/bin:$PATH"
[ -x "$HOME_DIR/.venv/bin/python" ] || uv venv --python 3.12 "$HOME_DIR/.venv"
uv pip install --python "$HOME_DIR/.venv/bin/python" -r "$HOME_DIR/requirements.txt"

# ── 5. Models (about 1 GB: ears, voice, wake helpers) ────────────────
say "Downloading the ears and the voice (one time, shows a real percentage)"
export HF_HOME="$HOME_DIR/models"
(cd "$HOME_DIR" && "$HOME_DIR/.venv/bin/python" setup_models.py)

# ── 6. Build the app (ad-hoc signed) ─────────────────────────────────
say "Building Alfred.app (about 2 minutes)"
( cd "$SRC/mac-app" && SIGN_ID="${SIGN_ID:--}" INSTALL=1 bash build.sh )

# ── 7. Sign in to Claude (your own account) ──────────────────────────
say "Claude sign-in"
bash "$HOME_DIR/ensure_claude.sh" || echo "You can sign in later from Alfred's setup guide."

say "Done"
echo "Open Alfred from Applications. The first launch from source: right-click the app → Open."
echo "macOS will ask for Microphone and Accessibility; Alfred's guide shows you where."
open -a Alfred || true
