#!/usr/bin/env node
// caveman — optional Rovo Dev on_session_start activation hook
//
// When wired into ~/.rovodev/config.yml as an on_session_start hook:
//   - Writes a flag file at ~/.rovodev/.caveman-active so external
//     scripts can detect that caveman mode is loaded
//   - Logs a short ruleset reminder (Rovo Dev hook stdout goes to
//     the event hooks log file, not agent context — the skill itself
//     provides the actual rules via get_skill("caveman"))
//
// This is a pure addition — if you don't wire it up, nothing changes.
// Install instructions: see the "Rovo Dev" section in hooks/README.md.

const fs = require('fs');
const path = require('path');
const os = require('os');

const flagPath = path.join(os.homedir(), '.rovodev', '.caveman-active');

try {
  fs.mkdirSync(path.dirname(flagPath), { recursive: true });
  fs.writeFileSync(flagPath, 'full');
} catch (e) {
  // Silent fail -- flag is best-effort, don't block the hook
}

// Note: unlike Claude Code, Rovo Dev hook stdout goes to the log file,
// not agent context. The skill provides the actual caveman rules.
process.stdout.write(
  "CAVEMAN MODE ACTIVE. Flag written to ~/.rovodev/.caveman-active\n"
);
