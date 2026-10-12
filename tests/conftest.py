"""Shared pytest configuration for VerityID tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests requiring a running GenLayer simulator (run with gltest)",
    )
