#!/bin/bash
# caveman — one-command hook installer for Rovo Dev
# Installs: on_session_start hook (flag file) + on_user_prompt hook (mode tracking)
# Also installs the caveman skill if not already present.
# Usage: bash hooks/rovodev/install.sh
#   or:  bash <(curl -s https://raw.githubusercontent.com/gad0lin/caveman/main/hooks/rovodev/install.sh)
set -e

ROVODEV_DIR="$HOME/.rovodev"
AGENTS_DIR="$HOME/.agents"
HOOKS_DIR="$ROVODEV_DIR/hooks"
SKILLS_DIR="$AGENTS_DIR/skills/caveman"
CONFIG="$ROVODEV_DIR/config.yml"
REPO_URL="https://raw.githubusercontent.com/gad0lin/caveman/main"

HOOK_FILES=("caveman-activate.js" "caveman-mode-tracker.js")

# Resolve source — works from repo clone or curl pipe
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" 2>/dev/null)" 2>/dev/null && pwd)"

echo "Installing caveman for Rovo Dev..."

# 1. Install skill
mkdir -p "$SKILLS_DIR"
if [ -f "$SCRIPT_DIR/../../skills/caveman/SKILL.md" ]; then
  cp "$SCRIPT_DIR/../../skills/caveman/SKILL.md" "$SKILLS_DIR/SKILL.md"
else
  curl -fsSL "$REPO_URL/skills/caveman/SKILL.md" -o "$SKILLS_DIR/SKILL.md"
fi
echo "  Installed skill: $SKILLS_DIR/SKILL.md"

# 2. Install hook scripts
mkdir -p "$HOOKS_DIR"
for hook in "${HOOK_FILES[@]}"; do
  if [ -f "$SCRIPT_DIR/$hook" ]; then
    cp "$SCRIPT_DIR/$hook" "$HOOKS_DIR/$hook"
  else
    curl -fsSL "$REPO_URL/hooks/rovodev/$hook" -o "$HOOKS_DIR/$hook"
  fi
  echo "  Installed hook: $HOOKS_DIR/$hook"
done

# 3. Install prompt template for !caveman
PROMPTS_DIR="$ROVODEV_DIR/prompts"
PROMPTS_YML="$ROVODEV_DIR/prompts.yml"
mkdir -p "$PROMPTS_DIR"
if [ -f "$SCRIPT_DIR/caveman-prompt.md" ]; then
  cp "$SCRIPT_DIR/caveman-prompt.md" "$PROMPTS_DIR/caveman.md"
else
  curl -fsSL "$REPO_URL/hooks/rovodev/caveman-prompt.md" -o "$PROMPTS_DIR/caveman.md"
fi
echo "  Installed prompt: $PROMPTS_DIR/caveman.md"

# Add prompt entry to prompts.yml if not already present
if [ -f "$PROMPTS_YML" ]; then
  if ! grep -q "name: caveman" "$PROMPTS_YML" 2>/dev/null; then
    cat >> "$PROMPTS_YML" << 'PROMPT_ENTRY'

- name: caveman
  description: "Activate caveman mode — ultra-compressed communication (~75% fewer tokens)"
  content_file: prompts/caveman.md
PROMPT_ENTRY
    echo "  Registered prompt in prompts.yml"
  else
    echo "  Prompt already registered in prompts.yml"
  fi
else
  cat > "$PROMPTS_YML" << 'PROMPT_ENTRY'
prompts:
- name: caveman
  description: "Activate caveman mode — ultra-compressed communication (~75% fewer tokens)"
  content_file: prompts/caveman.md
PROMPT_ENTRY
  echo "  Created prompts.yml with caveman prompt"
fi

# 4. Wire hooks into config.yml (idempotent)
if [ ! -f "$CONFIG" ]; then
  echo "{}" > "$CONFIG"
fi

# Check if yq is available, otherwise fall back to simple append
if command -v yq &> /dev/null; then
  # Use yq for proper YAML manipulation
  # Add on_session_start hook if not already present
  if ! yq '.eventHooks.events[] | select(.name == "on_session_start") | .commands[] | select(.command | contains("caveman"))' "$CONFIG" 2>/dev/null | grep -q "caveman"; then
    yq -i '
      .eventHooks.events += [{"name": "on_session_start", "commands": [{"command": "node '"$HOOKS_DIR"'/caveman-activate.js"}]}]
    ' "$CONFIG" 2>/dev/null || true
  fi

  # Add on_user_prompt hook if not already present
  if ! yq '.eventHooks.events[] | select(.name == "on_user_prompt") | .commands[] | select(.command | contains("caveman"))' "$CONFIG" 2>/dev/null | grep -q "caveman"; then
    yq -i '
      .eventHooks.events += [{"name": "on_user_prompt", "commands": [{"command": "node '"$HOOKS_DIR"'/caveman-mode-tracker.js"}]}]
    ' "$CONFIG" 2>/dev/null || true
  fi
  echo "  Hooks wired in config.yml"
else
  echo ""
  echo "  ⚠ yq not found — skipping automatic config.yml wiring."
  echo "  Add the following to $CONFIG manually, or use /hooks in Rovo Dev:"
  echo ""
  echo "  eventHooks:"
  echo "    events:"
  echo "      - name: \"on_session_start\""
  echo "        commands:"
  echo "          - command: \"node $HOOKS_DIR/caveman-activate.js\""
  echo "      - name: \"on_user_prompt\""
  echo "        commands:"
  echo "          - command: \"node $HOOKS_DIR/caveman-mode-tracker.js\""
  echo ""
  echo "  Or just run /hooks inside Rovo Dev to configure interactively."
fi

echo ""
echo "Done! Restart Rovo Dev to activate."
echo ""
echo "What's installed:"
echo "  - Skill: caveman rules loaded via get_skill(\"caveman\")"
echo "  - Prompt: !caveman (prompt shortcut in TUI)"
echo "  - on_session_start hook: writes flag file on session start"
echo "  - on_user_prompt hook: tracks mode changes (/caveman lite, ultra, etc.)"
echo ""
echo "Usage in Rovo Dev:"
echo "  - !caveman — activate via prompt shortcut"
echo "  - !caveman ultra — activate ultra mode"
echo "  - Say \"caveman mode\" or load with get_skill(\"caveman\")"
echo "  - Deactivate: say \"stop caveman\" or \"normal mode\""
