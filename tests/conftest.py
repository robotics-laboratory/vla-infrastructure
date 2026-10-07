"""Keep native Isaac tests explicit instead of treating their skips as core coverage."""
from pathlib import Path

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(item.path).name == 'test_isaac_s2_upstream.py':
            item.add_marker(pytest.mark.isaac_upstream)
