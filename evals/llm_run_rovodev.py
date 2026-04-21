"""
Caveman eval runner for Rovo Dev.

Two modes:
  --mode=serve   (default) Fast — uses acli rovodev serve HTTP API. Start server first:
                   acli rovodev serve 18899 --disable-session-token --non-interactive &
  --mode=legacy  Slow — spawns acli rovodev legacy per prompt (~90s each)

Usage:
    uv run python evals/llm_run_rovodev.py                           # serve mode, all arms
    uv run python evals/llm_run_rovodev.py --arms caveman            # single arm
    uv run python evals/llm_run_rovodev.py --mode=legacy             # legacy CLI mode
    uv run python evals/llm_run_rovodev.py --port 8888               # custom serve port
    uv run python evals/llm_run_rovodev.py --dry-run                 # show what would run

Then measure:
    uv run --with tiktoken python evals/measure.py --snapshot evals/snapshots/results_rovodev.json

Logs:
    evals/snapshots/rovodev_eval.log   — detailed per-call log with timing, stderr, response preview
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

EVALS = Path(__file__).parent
PROMPTS = EVALS / "prompts" / "en.txt"
SNAPSHOT = EVALS / "snapshots" / "results_rovodev.json"
LOG_FILE = EVALS / "snapshots" / "rovodev_eval.log"
SKILL = Path(__file__).resolve().parent.parent / "skills" / "caveman" / "SKILL.md"

# Set up dual logging: console (INFO) + file (DEBUG)
log = logging.getLogger("caveman-eval")
log.setLevel(logging.DEBUG)

_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_console)

_file = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_file.setLevel(logging.DEBUG)
_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s"))
log.addHandler(_file)


def run_legacy(prompt: str, system_prefix: str | None = None) -> dict:
    """Run a single prompt via acli rovodev legacy. Returns result dict with metadata."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        out_path = f.name

    full_prompt = prompt
    if system_prefix:
        full_prompt = f"{system_prefix}\n\nQuestion: {prompt}"

    cmd = [
        "acli", "rovodev", "legacy",
        "--yolo",
        "--output-file", out_path,
        full_prompt,
    ]

    log.debug("CMD: %s", " ".join(cmd[:5]) + f" '<prompt len={len(full_prompt)}>'")

    t0 = time.time()
    result = {
        "response": "",
        "elapsed_s": 0.0,
        "exit_code": None,
        "stderr_tail": "",
        "status": "ok",
    }

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        result["exit_code"] = proc.returncode
        result["response"] = Path(out_path).read_text().strip()
        result["stderr_tail"] = (proc.stderr or "")[-500:]  # last 500 chars of stderr

        if proc.returncode != 0:
            result["status"] = f"exit_code={proc.returncode}"
            log.debug("STDERR (last 500): %s", result["stderr_tail"])

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["response"] = "[TIMEOUT]"
        log.warning("TIMEOUT after 180s")
    except Exception as e:
        result["status"] = f"error: {e}"
        result["response"] = f"[ERROR: {e}]"
        log.error("EXCEPTION: %s", e)
    finally:
        result["elapsed_s"] = round(time.time() - t0, 1)
        Path(out_path).unlink(missing_ok=True)

    return result


def rovodev_version() -> str:
    """Get the acli rovodev version string."""
    try:
        r = subprocess.run(
            ["acli", "rovodev", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() or r.stderr.strip() or "unknown"
    except Exception:
        return "unknown"


def run_serve(prompt: str, system_prefix: str | None, base_url: str) -> dict:
    """Run a single prompt via the serve API. Returns result dict with metadata."""
    t0 = time.time()
    result = {
        "response": "",
        "elapsed_s": 0.0,
        "status": "ok",
        "input_tokens": 0,
        "output_tokens": 0,
    }

    try:
        # Reset agent history to isolate each prompt
        clear_req = urllib.request.Request(
            f"{base_url}/v3/clear",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(clear_req, timeout=30)

        # Set system prompt (or clear it)
        sp_body = json.dumps({"prompt": system_prefix or ""}).encode()
        sp_req = urllib.request.Request(
            f"{base_url}/v3/inline-system-prompt",
            data=sp_body,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(sp_req, timeout=10)

        # Set chat message
        cm_body = json.dumps({"message": prompt}).encode()
        cm_req = urllib.request.Request(
            f"{base_url}/v3/set_chat_message",
            data=cm_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(cm_req, timeout=10)

        # Stream response
        stream_req = urllib.request.Request(f"{base_url}/v3/stream_chat")
        with urllib.request.urlopen(stream_req, timeout=180) as resp:
            text_parts = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                # Collect text content
                # part_start: {"part": {"content": "...", "part_kind": "text"}, "event_kind": "part_start"}
                part = data.get("part", {})
                if part.get("part_kind") == "text" and part.get("content"):
                    text_parts.append(part["content"])
                # part_delta: {"delta": {"content_delta": "...", "part_delta_kind": "text"}, "event_kind": "part_delta"}
                delta = data.get("delta", {})
                if delta.get("content_delta"):
                    text_parts.append(delta["content_delta"])
                # Collect token usage
                elif "output_tokens" in data:
                    result["input_tokens"] = data.get("input_tokens", 0)
                    result["output_tokens"] = data.get("output_tokens", 0)

            result["response"] = "".join(text_parts).strip()

    except urllib.error.URLError as e:
        result["status"] = f"connection_error: {e}"
        result["response"] = f"[ERROR: {e}]"
        log.error("SERVE ERROR: %s", e)
    except Exception as e:
        result["status"] = f"error: {e}"
        result["response"] = f"[ERROR: {e}]"
        log.error("SERVE EXCEPTION: %s", e)
    finally:
        result["elapsed_s"] = round(time.time() - t0, 1)

    return result


def build_arms() -> dict[str, str | None]:
    """Return arm name -> system prefix mapping."""
    skill_text = SKILL.read_text().strip()

    return {
        "baseline": None,
        "terse": "Answer concisely.",
        "caveman": skill_text,
    }


def main() -> None:
    prompts = [p.strip() for p in PROMPTS.read_text().splitlines() if p.strip()]
    all_arms = build_arms()

    # Parse args
    dry_run = "--dry-run" in sys.argv
    mode = "serve"
    port = 18899
    selected = None

    for i, arg in enumerate(sys.argv):
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
        elif arg == "--arms" and i + 1 < len(sys.argv):
            selected = sys.argv[i + 1].split(",")

    base_url = f"http://localhost:{port}"
    arms_to_run = {k: v for k, v in all_arms.items() if selected is None or k in selected}

    if dry_run:
        log.info("Would run %d arms × %d prompts = %d calls (mode=%s)", len(arms_to_run), len(prompts), len(arms_to_run) * len(prompts), mode)
        for arm in arms_to_run:
            log.info("  - %s", arm)
        return

    # Check serve mode connectivity
    if mode == "serve":
        try:
            urllib.request.urlopen(f"{base_url}/healthcheck", timeout=5)
        except Exception:
            log.error("Cannot reach %s — start the server first:", base_url)
            log.error("  acli rovodev serve %d --disable-session-token --non-interactive &", port)
            return

    version = rovodev_version()
    log.info("=" * 60)
    log.info("Caveman Eval — Rovo Dev (%s mode)", mode)
    log.info("=" * 60)
    log.info("CLI:     %s", version)
    log.info("Mode:    %s%s", mode, f" ({base_url})" if mode == "serve" else "")
    log.info("Arms:    %s", list(arms_to_run.keys()))
    log.info("Prompts: %d", len(prompts))
    log.info("Log:     %s", LOG_FILE)
    log.info("")

    results: dict[str, list[str]] = {}
    run_log: list[dict] = []
    total_calls = sum(len(prompts) for _ in arms_to_run)
    call_num = 0

    for arm_name, system in arms_to_run.items():
        results[arm_name] = []
        log.info("── arm: %s ──", arm_name)
        arm_start = time.time()

        for i, prompt in enumerate(prompts, 1):
            call_num += 1
            log.info("  [%d/%d] %s", call_num, total_calls, prompt[:60])
            log.debug("  FULL PROMPT: %s", prompt)

            if mode == "serve":
                r = run_serve(prompt, system, base_url)
            else:
                r = run_legacy(prompt, system)

            results[arm_name].append(r["response"])

            # Console output
            preview = r["response"][:80].replace("\n", " ")
            token_info = ""
            if r.get("output_tokens"):
                token_info = f", {r['output_tokens']} out_tokens"
            log.info("    → %s (%.1fs, %d chars%s)", r["status"], r["elapsed_s"], len(r["response"]), token_info)
            log.debug("    RESPONSE PREVIEW: %s", preview)

            # Detailed log entry
            entry = {
                "arm": arm_name,
                "prompt_idx": i,
                "prompt": prompt,
                "status": r["status"],
                "elapsed_s": r["elapsed_s"],
                "response_len": len(r["response"]),
                "response_preview": preview,
            }
            if mode == "serve":
                entry["input_tokens"] = r.get("input_tokens", 0)
                entry["output_tokens"] = r.get("output_tokens", 0)
            else:
                entry["exit_code"] = r.get("exit_code")
                entry["stderr_tail"] = (r.get("stderr_tail") or "")[:200]
            run_log.append(entry)

        arm_elapsed = time.time() - arm_start
        log.info("  arm %s done in %.0fs\n", arm_name, arm_elapsed)

    # Save snapshot
    snapshot = {
        "metadata": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "model": "Rovo Dev (acli rovodev legacy)",
            "cli": version,
            "total_calls": total_calls,
            "run_log": run_log,
        },
        "arms": {
            name: {"responses": resps}
            for name, resps in results.items()
        },
    }

    SNAPSHOT.write_text(json.dumps(snapshot, indent=2))
    log.info("Snapshot saved to %s", SNAPSHOT)
    log.info("Detailed log at %s", LOG_FILE)
    log.info("")
    log.info("Measure with:")
    log.info("  uv run --with tiktoken python evals/measure.py --snapshot %s", SNAPSHOT)

    # Print summary table
    log.info("")
    log.info("── Summary ──")
    for arm_name in results:
        arm_entries = [e for e in run_log if e["arm"] == arm_name]
        total_time = sum(e["elapsed_s"] for e in arm_entries)
        total_chars = sum(e["response_len"] for e in arm_entries)
        errors = sum(1 for e in arm_entries if e["status"] != "ok")
        log.info("  %s: %d chars total, %.0fs, %d errors", arm_name, total_chars, total_time, errors)


if __name__ == "__main__":
    main()
