#!/usr/bin/env bash
# Builds an UNSIGNED Alfred.dmg (app only, small). Python and models download on first run. Deletes nothing.
# Usage: bash mac-app/make-dmg.sh      -> dist/Alfred.dmg      (nothing is uploaded or published)
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
bash ./build.sh
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/alfred-dmg-stage.XXXXXX")"
mkdir -p "$ROOT/dist"
ditto --norsrc --noextattr --noqtn build/Alfred.app "$STAGE/Alfred.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/READ ME FIRST.txt" <<'TXT'
Alfred is not signed by Apple (the developer has no paid Apple account yet), so macOS blocks the first launch.
It is safe to open if you downloaded it from the official Alfred page. Three steps:

 1. Drag Alfred into Applications, then double-click it. macOS says it can't verify it. Press Done.
 2. Open System Settings > Privacy & Security. Scroll down to "Alfred was blocked". Press "Open Anyway".
 3. Press "Open Anyway" once more and enter your Mac password. Alfred opens and guides you through setup.

You only do this once.
TXT
OUTDMG="$ROOT/dist/Alfred.dmg"
if [ -e "$OUTDMG" ]; then mkdir -p "$ROOT/to delete"; mv "$OUTDMG" "$ROOT/to delete/Alfred.dmg.$(date +%Y%m%d-%H%M%S)"; fi
hdiutil create -volname "Alfred" -srcfolder "$STAGE" -format UDZO -fs HFS+ "$OUTDMG" >/dev/null
echo "Built $OUTDMG ($(du -sh "$OUTDMG" | cut -f1)) — unsigned, not notarized."
shasum -a 256 "$OUTDMG"
