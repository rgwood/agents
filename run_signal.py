#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv",
# ]
# ///
"""
Wrapper script to run signal_agent.py within srt sandbox.

Loads environment variables before sandboxing, then invokes the agent
with OS-level filesystem and network restrictions.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables first (before sandboxing restricts file access)
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Paths
SETTINGS_PATH = SCRIPT_DIR / ".srt-settings.json"
AGENT_PATH = SCRIPT_DIR / "signal_agent.py"


def main():
    # Build the command
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Report on the last 24 hours."

    cmd = [
        "srt",
        "--settings", str(SETTINGS_PATH),
        "uv", "run", str(AGENT_PATH), prompt
    ]

    # Pass through environment variables
    env = os.environ.copy()

    # Execute within sandbox
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
