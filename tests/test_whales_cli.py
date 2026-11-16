# ABOUTME: Tests the whale-hunting CLI argument parsing.
# ABOUTME: Past-date and abbreviated flags must be rejected before any data is fetched.

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / ".claude/skills/whale-hunting/scripts/whale_hunting.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60
    )


def test_date_flag_is_rejected():
    result = _run("NVDA", "--date", "2026-11-13")
    assert result.returncode == 2
    assert "unrecognized arguments: --date" in result.stderr


def test_abbreviated_sigma_flag_is_rejected():
    result = _run("NVDA", "--sigma", "2.0")
    assert result.returncode == 2
    assert "unrecognized arguments: --sigma" in result.stderr
