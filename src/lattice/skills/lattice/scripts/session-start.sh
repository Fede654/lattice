#!/usr/bin/env bash
# session-start.sh — Claude Code SessionStart hook.
#
# Prints one line of context when the session opens inside a Lattice project,
# so the agent knows a board exists before it does anything. Prints nothing —
# and costs nothing — anywhere else. Installed into ~/.claude/settings.json by
# `lattice setup-claude-skill`.
set -uo pipefail

dir="$PWD"
while [ "$dir" != "/" ]; do
  if [ -d "$dir/.lattice" ]; then
    code=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_code',''))" "$dir/.lattice/config.json" 2>/dev/null)
    open=""
    if command -v lattice >/dev/null 2>&1; then
      open=$(cd "$dir" && lattice list --json 2>/dev/null \
        | python3 -c "import json,sys; d=json.load(sys.stdin); d['ok'] or sys.exit(1); print(len(d['data']))" 2>/dev/null)
    fi
    printf 'Lattice board %s at %s' "${code:-?}" "$dir"
    [ -n "$open" ] && printf ' — %s open tasks' "$open"
    printf '. This project tracks all work in Lattice: load the `lattice` skill before writing code or reporting state.\n'
    exit 0
  fi
  dir=$(dirname "$dir")
done
exit 0
