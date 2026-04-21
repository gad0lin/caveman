#!/usr/bin/env bash
# ============================================================================
# Caveman Eval Runner for Rovo Dev
# ============================================================================
# Runs the 3-arm caveman eval (baseline/terse/caveman) against the Rovo Dev
# serve API. Automatically manages hooks to avoid contamination.
#
# Usage:
#   bash evals/run-rovodev-eval.sh           # full eval (3 arms × 10 prompts)
#   bash evals/run-rovodev-eval.sh --arms caveman  # single arm
#   bash evals/run-rovodev-eval.sh --dry-run       # preview only
#
# Prerequisites:
#   - acli rovodev installed and authenticated
#   - uv installed (for Python deps)
#
# ============================================================================
set -euo pipefail

PORT="${CAVEMAN_EVAL_PORT:-18899}"
CONFIG="$HOME/.rovodev/config.yml"
CONFIG_BAK="$HOME/.rovodev/config.yml.eval-backup"
FLAG_FILE="$HOME/.rovodev/.caveman-active"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRA_ARGS="${*}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Caveman Eval — Rovo Dev                            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Disable hooks to prevent contamination ──────────────
echo "▸ Step 1: Disabling caveman hooks..."

hooks_disabled=false

if [ -f "$CONFIG" ] && grep -q "caveman" "$CONFIG" 2>/dev/null; then
    cp "$CONFIG" "$CONFIG_BAK"
    # Remove caveman hook entries (both on_session_start and on_user_prompt)
    if command -v yq &>/dev/null; then
        yq -i 'del(.eventHooks.events[] | select(.commands[].command | test("caveman")))' "$CONFIG" 2>/dev/null || true
    else
        # Fallback: comment out caveman lines
        sed -i.tmp 's/.*caveman.*/#&/' "$CONFIG" 2>/dev/null || true
        rm -f "${CONFIG}.tmp"
    fi
    hooks_disabled=true
    echo "  ✓ Hooks backed up to $CONFIG_BAK"
    echo "  ✓ Caveman hooks removed from config"
else
    echo "  ✓ No caveman hooks found — clean config"
fi

# Remove flag file
rm -f "$FLAG_FILE"
echo "  ✓ Flag file removed"
echo ""

# ── Step 2: Start serve (or use existing) ───────────────────────
echo "▸ Step 2: Starting Rovo Dev server on port $PORT..."

server_started=false

if curl -s "http://localhost:$PORT/healthcheck" &>/dev/null; then
    echo "  ✓ Server already running on port $PORT"
    echo "  ⚠ Warning: restarting to ensure clean state (no cached hooks)"
    pkill -f "rovodev serve" 2>/dev/null || true
    sleep 3
fi

acli rovodev serve "$PORT" --disable-session-token --non-interactive &
SERVER_PID=$!
server_started=true

echo "  Server PID: $SERVER_PID"
echo "  Waiting for healthcheck..."

for i in $(seq 1 30); do
    if curl -s "http://localhost:$PORT/healthcheck" &>/dev/null; then
        echo "  ✓ Server ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ✗ Server failed to start after 60s"
        exit 1
    fi
    sleep 2
done
echo ""

# ── Step 3: Run eval ────────────────────────────────────────────
echo "▸ Step 3: Running eval..."
echo ""

# shellcheck disable=SC2086
uv run python "$SCRIPT_DIR/llm_run_rovodev.py" --port "$PORT" $EXTRA_ARGS

echo ""

# ── Step 4: Measure results ─────────────────────────────────────
echo "▸ Step 4: Measuring token counts..."
echo ""

SNAPSHOT="$SCRIPT_DIR/snapshots/results_rovodev.json"
if [ -f "$SNAPSHOT" ]; then
    # Use API-reported tokens from the run log
    echo "── Token Summary (API-reported) ──"
    jq -r '
      .metadata.run_log | group_by(.arm) | sort_by(.[0].arm) | .[] |
      (.[0].arm) as $arm |
      (map(.output_tokens)) as $t |
      "  \($arm): avg \($t | add / length | floor) tokens/response, total \($t | add) tokens"
    ' "$SNAPSHOT"
    echo ""

    # Also run tiktoken measure for comparison
    uv run --with tiktoken python "$SCRIPT_DIR/measure.py" --snapshot "$SNAPSHOT" 2>/dev/null || true

    # Generate plots
    echo ""
    echo "▸ Step 4b: Generating plots..."
    uv run --with plotly --with kaleido python "$SCRIPT_DIR/plot_rovodev.py" 2>/dev/null || \
    uv run --with plotly python "$SCRIPT_DIR/plot_rovodev.py" 2>/dev/null || \
    echo "  ⚠ Plot generation failed (install plotly: uv pip install plotly kaleido)"
fi

# ── Step 5: Cleanup ─────────────────────────────────────────────
echo ""
echo "▸ Step 5: Cleanup..."

# Stop server
if [ "$server_started" = true ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    echo "  ✓ Server stopped"
fi

# Restore hooks
if [ "$hooks_disabled" = true ] && [ -f "$CONFIG_BAK" ]; then
    cp "$CONFIG_BAK" "$CONFIG"
    rm -f "$CONFIG_BAK"
    echo "  ✓ Hooks restored from backup"
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Done!                                              ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Snapshot: evals/snapshots/results_rovodev.json     ║"
echo "║  Log:      evals/snapshots/rovodev_eval.log         ║"
echo "╚══════════════════════════════════════════════════════╝"
