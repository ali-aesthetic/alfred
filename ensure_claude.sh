#!/bin/bash
# Installs Claude Code (if missing) and checks that you are signed in with your own Claude account.
# Alfred never sees your login: you sign in once in Anthropic's own browser page, run by the `claude` tool.
source "$(cd "$(dirname "$0")" && pwd)/env.sh"
mkdir -p "$J/data"
if ! command -v claude >/dev/null 2>&1; then
  echo "Installing Claude Code (Alfred's brain)…"
  curl -fsSL https://claude.ai/install.sh | bash
  export PATH="$HOME/.local/bin:$PATH"
fi
check() {
  out=$(cd "$J/data" && env -u ANTHROPIC_API_KEY claude -p "Reply with one word: ok" --output-format json 2>/dev/null)
  echo "$out" | grep -q '"is_error":false'
}
if check; then echo "✓ Claude Code is connected to your account."; exit 0; fi
echo
echo "════════════════════════════════════════════════════════════"
echo " One-time sign-in to your Claude account."
echo " Claude Code opens next. If it does not ask by itself, type"
echo "  /login , choose your Claude subscription, approve in the"
echo " browser, then type  /exit"
echo "════════════════════════════════════════════════════════════"
read -n 1 -s -r -p "Press any key to start the sign-in…"; echo
(cd "$J/data" && env -u ANTHROPIC_API_KEY claude)
if check; then echo "✓ Signed in."; else echo "⚠ Sign-in not confirmed. Try again later: bash \"$J/ensure_claude.sh\""; exit 1; fi
