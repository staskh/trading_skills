# ABOUTME: Tests for the package metadata in pyproject.toml.
# ABOUTME: Guards that libraries imported by runtime code are runtime dependencies.

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _runtime_dependencies() -> list[str]:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    return [dep.split(">")[0].split("=")[0].strip() for dep in project["dependencies"]]


def test_python_dotenv_is_a_runtime_dependency():
    """broker.connection and massive.whales import dotenv outside of tests."""
    assert "python-dotenv" in _runtime_dependencies()
