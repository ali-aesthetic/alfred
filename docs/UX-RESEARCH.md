# UX research: progress and onboarding (what we took, what we left)

Date: 2026-11-23. Short, source-based. Sources: Apple Human Interface Guidelines, [Progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators.md) and [Loading](https://developer.apple.com/design/human-interface-guidelines/loading.md); AppKit [NSProgressIndicator](https://developer.apple.com/documentation/appkit/nsprogressindicator.md); onboarding patterns seen in open-source Mac agent apps (OpenClaw, OpenAra: permission steps, drag-icon hint, live permission check, separate "fix permissions later" mode).

## Progress (downloads and first launch)
| Idea | Source | Done in Alfred |
|---|---|---|
| Use a **determinate** bar whenever you can measure progress; indeterminate only when you cannot, and switch to determinate as soon as you can | HIG | ✅ bytes from the downloads, package counts from `uv`; the "resolving packages" phase is honestly shown as "Working…" until measurable |
| Pair the bar with short text (Finder style): what, how much, how long | HIG (Finder copy) | ✅ "Ears (Whisper small): 197 MB of 480 MB · about 12 seconds left" |
| Show the real percent as a number too | common practice | ✅ big % next to the bar, with a VoiceOver label |
| Let people pause / retry long work | common practice | ✅ Pause really suspends the work; Retry resumes (finished files are skipped); closing the window does not stop the download |
| Name the current step, list the steps with ticks | installers | ✅ 3 steps, tick when done |
| No fake spinners / invented percentages | HIG + brief | ✅ the only spinner is the small one shown while a phase cannot be measured, with words saying so |
| Respect **Reduce Motion** | accessibility | ✅ bar animation off when Reduce Motion is on; no other motion used |
| Say what to do on failure, in plain words | HIG (errors) | ✅ message + Retry; Help → Troubleshooting |

Left out on purpose: confetti, animated mascots, bouncing bars, percentages that jump to 90% (fake progress), a circular spinner for long jobs.

## Onboarding and permissions
| Idea | Done |
|---|---|
| One step per screen, a dot/bar showing "step 3 of 7" | ✅ |
| Check the Mac first (macOS 14+, Apple Silicon, free disk) so people do not fail 10 minutes later | ✅ |
| Do the long download early, while the person does other steps | ✅ download starts on step 1 (you can continue to sign-in and permissions while it runs: "Continue when finished" only gates the last step) |
| Permissions: one row each, say **why**, deep-link to the exact System Settings pane, live-detect when it is granted (poll once a second) | ✅ |
| Show a **picture** of what they will see | ✅ drawn mock of the Settings pane with the Alfred switch highlighted |
| Optional permissions can be skipped | ✅ Screen Recording and Input Monitoring marked optional; "Continue anyway" |
| A way back later | ✅ Help → "Show setup guide again" and the Help menu |
| Never ask for credentials in-app | ✅ Claude sign-in happens on Anthropic's own page, started by the `claude` tool |

## Not verified
Layout was built from the research above and compiled; it has **not** been user-tested with first-time users. A first-run test with 2–3 people who have never seen Alfred is the next best investment.
