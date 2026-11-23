#!/bin/bash
# Optional: start Alfred when you log in (current Mac user, no password needed).
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
chmod +x "$J/alfred.command" "$J/install.sh" "$J/ensure_claude.sh" "$J/bin/alfred-say" 2>/dev/null
PLIST="$HOME/Library/LaunchAgents/com.alfred.assistant.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alfred.assistant</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string><string>-g</string><string>-a</string><string>Terminal</string>
    <string>$J/alfred.command</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOP
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST"
echo "✓ Autostart on for user $USER. To turn off: launchctl unload \"$PLIST\""
