#!/usr/bin/env bash
# Builds Alfred.app (no Apple Developer account needed). Deletes nothing: anything in the way is moved to ../to delete.
#   bash build.sh                 -> mac-app/build/Alfred.app   (ad-hoc signed, runs on this Mac)
#   INSTALL=1 bash build.sh       -> also installs to /Applications
#   SIGN_ID="Developer ID Application: NAME (TEAMID)" bash build.sh   -> real signing, later, with an Apple account
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
SIGN_ID="${SIGN_ID:--}"                       # "-" = ad-hoc
TD="$HERE/../to delete"
OUT="$HERE/build"
STAMP=$(date +%Y%m%d-%H%M%S)
WORK="$(mktemp -d "${TMPDIR:-/tmp}/alfred-app-build.XXXXXX")"   # fresh folder outside Desktop/iCloud (they add attributes that break signing)
APP="$WORK/Alfred.app"
mkdir -p "$OUT"

SCR=(); [ -n "${SCRATCH:-}" ] && SCR=(--scratch-path "$SCRATCH")   # optional: build in a different folder
swift build -c release ${SCR[@]+"${SCR[@]}"}
BINDIR=$(swift build -c release ${SCR[@]+"${SCR[@]}"} --show-bin-path)

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BINDIR/Alfred" "$APP/Contents/MacOS/Alfred"
cp "$BINDIR/alfred-ctl" "$APP/Contents/MacOS/alfred-ctl"
cp Info.plist "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
swift make_icon.swift "$WORK/AppIcon.iconset" && iconutil -c icns "$WORK/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
bash "$HERE/bundle-brain.sh" "$APP/Contents/Resources/brain"

xattr -cr "$APP"
OPTS=(--force --sign "$SIGN_ID")
[ "$SIGN_ID" != "-" ] && OPTS+=(--options runtime --timestamp)
codesign "${OPTS[@]}" --identifier com.alfred.app.ctl "$APP/Contents/MacOS/alfred-ctl"
codesign "${OPTS[@]}" --identifier com.alfred.app "$APP"
codesign --verify --strict "$APP"
echo "Signed with: $([ "$SIGN_ID" = "-" ] && echo 'ad-hoc (no Apple account)' || echo "$SIGN_ID")"

if [ -e "$OUT/Alfred.app" ]; then mkdir -p "$TD"; mv "$OUT/Alfred.app" "$TD/Alfred.app.build.$STAMP"; fi
ditto --norsrc --noextattr --noqtn "$APP" "$OUT/Alfred.app"
echo "Built $OUT/Alfred.app ($(du -sh "$OUT/Alfred.app" | cut -f1))"

if [ "${INSTALL:-0}" = "1" ]; then
  DEST="/Applications/Alfred.app"
  if pgrep -x Alfred >/dev/null; then osascript -e 'tell application id "com.alfred.app" to quit' 2>/dev/null || true; sleep 3; fi
  if [ -e "$DEST" ]; then mkdir -p "$TD"; mv "$DEST" "$TD/Alfred.app.$STAMP"; echo "Moved the old app to $TD/Alfred.app.$STAMP"; fi
  ditto --norsrc --noextattr --noqtn "$APP" "$DEST"
  echo "Installed $DEST"
fi
