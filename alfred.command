#!/bin/bash
# Runs Alfred's brain in a window and restarts it if it crashes. Home = $ALFRED_HOME.
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
export HF_HUB_OFFLINE=1
cd "$J" || exit 1
printf '\033]0;Alfred\007'
trap 'kill $PY_PID 2>/dev/null; pkill -f "[A]lfred/boot_hud.py"; exit 0' HUP INT TERM
while true; do
  "$J/.venv/bin/python" "$J/alfred.py" "$@" &
  PY_PID=$!
  wait $PY_PID
  code=$?
  if [ "$code" -eq 42 ]; then echo "Alfred is off. You can close this window."; exit 0; fi
  [ -f "$J/data/STOP" ] && { echo "Stopped."; exit 0; }
  echo "Alfred crashed (code $code). Restarting in 3 seconds…"; sleep 3
done
