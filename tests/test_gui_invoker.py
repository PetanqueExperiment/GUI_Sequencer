"""GuiThreadInvoker: work from a worker thread runs on the Qt thread (QCoreApplication, no window)."""

from __future__ import annotations

import threading
import time

import pytest
from PyQt5.QtCore import QCoreApplication, QThread

from sequencer_gui.remote_control.gui_invoker import GuiCallTimeout, GuiThreadInvoker


def _from_worker(app: QCoreApplication, fn, *, run_loop_s: float = 2.0):
    """Run ``fn`` in a worker thread while the Qt event loop is pumped here; return its outcome."""
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["result"] = fn()
        except BaseException as e:
            outcome["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    deadline = time.monotonic() + run_loop_s
    while t.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    t.join(timeout=5.0)
    return outcome


def test_runs_on_gui_thread_and_returns(app: QCoreApplication) -> None:
    invoker = GuiThreadInvoker()
    gui_thread = QThread.currentThread()
    out = _from_worker(app, lambda: invoker.call(lambda: QThread.currentThread() == gui_thread))
    assert out == {"result": True}


def test_exception_is_reraised_in_caller(app: QCoreApplication) -> None:
    invoker = GuiThreadInvoker()

    def boom() -> None:
        raise ValueError("bad label")

    out = _from_worker(app, lambda: invoker.call(boom))
    assert isinstance(out["error"], ValueError)


def test_failed_call_frees_caller_frame_without_gc(app: QCoreApplication) -> None:
    """A stored exception must not keep the caller's locals alive (HEROS: zenoh query → 10 s stall)."""
    import gc
    import weakref

    class Query:  # stands in for the zenoh query held by the HEROS call frame
        pass

    invoker = GuiThreadInvoker()

    def boom() -> None:
        raise ValueError("bad")

    def heros_call() -> weakref.ref:
        query = Query()
        ref = weakref.ref(query)
        try:
            invoker.call(boom)
        except ValueError:
            pass
        return ref

    gc.disable()
    try:
        out = _from_worker(app, heros_call)
        assert out["result"]() is None
    finally:
        gc.enable()


def test_call_from_gui_thread_runs_directly(app: QCoreApplication) -> None:
    assert GuiThreadInvoker().call(lambda: 42) == 42


def test_timeout_before_start_cancels_the_call(app: QCoreApplication) -> None:
    invoker = GuiThreadInvoker()
    ran = []
    # Event loop not pumped while the worker waits: the call never starts, so it must not run later.
    out: dict = {}

    def worker() -> None:
        try:
            invoker.call(lambda: ran.append(1), timeout_s=0.05)
        except GuiCallTimeout as e:
            out["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    app.processEvents()
    assert "nothing was done" in str(out["error"])
    assert ran == []
