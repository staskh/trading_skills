# ABOUTME: Integration test for the whale-hunting CLI script's Yahoo-only fallback.
# ABOUTME: Verifies the script degrades gracefully (exit 0) when MASSIVE_API_KEY is unset.

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".claude" / "skills" / "whale-hunting" / "scripts" / "whale_hunting.py"


def test_missing_api_key_falls_back_to_yahoo_only():
    env = {k: v for k, v in os.environ.items() if k != "MASSIVE_API_KEY"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "NVDA", "--summary"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["source"] == "yahoo only"
    assert output["total_whales"] > 0
