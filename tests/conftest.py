"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from PyQt5.QtCore import QCoreApplication


@pytest.fixture(scope="session")
def app() -> QCoreApplication:
    """One Qt application kept alive for the whole test session (Qt allows only one)."""
    return QCoreApplication.instance() or QCoreApplication([])
