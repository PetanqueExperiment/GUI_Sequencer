"""Shared pytest fixtures."""

from __future__ import annotations

import sys
import types

import pytest
from PyQt5.QtCore import QCoreApplication


class _NoDevicesInTests:
    """Stands in for every HERO class: tests run on the lab PC next to the live experiment."""

    def __init__(self, name: str = "", *args, **kwargs) -> None:
        raise RuntimeError(
            f"tests must not reach HERO {name!r}; give the test a fake ``heros`` module"
        )


@pytest.fixture(autouse=True)
def no_real_hero_devices(monkeypatch):
    """Lazy ``from heros import RemoteHERO`` (PyCam, static devices, ARTIQ) fails in every test.

    Tests that need a device put their own fake in ``sys.modules["heros"]`` on top of this.
    """
    blocked = types.SimpleNamespace(
        RemoteHERO=_NoDevicesInTests, LocalHERO=_NoDevicesInTests, EventObserver=_NoDevicesInTests
    )
    monkeypatch.setitem(sys.modules, "heros", blocked)


@pytest.fixture(scope="session")
def app() -> QCoreApplication:
    """One Qt application kept alive for the whole test session (Qt allows only one)."""
    return QCoreApplication.instance() or QCoreApplication([])
