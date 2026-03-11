"""
conftest.py — pytest session setup.

Stubs out the `breeze_connect` C-extension package so that unit tests can
import backend modules without the real breeze_connect wheel being installed.
All tests that exercise Breeze API calls mock `get_session` directly, so this
stub is never actually called during tests.

On Render (and in the developer's local venv) the real package is installed and
this stub is not needed — it only activates when `breeze_connect` is absent.
"""

import sys
from unittest.mock import MagicMock

# Only inject the stub if the real package isn't available
try:
    import breeze_connect  # noqa: F401
except (ImportError, Exception):
    stub = MagicMock()
    stub.BreezeConnect = MagicMock
    sys.modules["breeze_connect"] = stub
