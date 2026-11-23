# Pointing: show, don't just tell

For "how do I...", "where is...", "show me..." questions about something on screen, point at it.

1. Find it: `alfred-ctl find "<title>" --app <App>` (or `alfred-ctl ui --app <App>` to scan the window). Output frame is `[x, y, w, h]` in screen points, top-left origin.
2. Centre = `x + w/2`, `y + h/2`. Point: `alfred-ctl point CX CY "label" "hint"`.
   - label: 6 words max, e.g. "Share button". hint: short, optional, e.g. "then Export File".
3. One step at a time. For several steps add `--step N --of M` (e.g. `--step 1 --of 3`).
4. After a multi-step point, wait for the `point_done` event (user clicked the ring) before the next step. If it takes over ~20 s, ask once if they need help.
5. Speak or write at most 12 words per step, e.g. "Step 1: click Share, top right."
6. Not found: say so in one line and suggest where to look ("Not seeing Export. Try the File menu."). Do not guess coordinates.
7. Done or user changed their mind: the pointer fades 3 s after the last step. Esc clears it. Never click for the user unless asked.
