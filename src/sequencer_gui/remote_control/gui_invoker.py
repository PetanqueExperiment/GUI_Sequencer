"""Run a callable on the Qt GUI thread from another thread and wait for its result.

HEROS serves remote calls on zenoh callback threads. ``SequenceAppState`` and every widget belong to
the GUI thread, so remote calls hand their work to :class:`GuiThreadInvoker`, which runs it from the
Qt event loop and passes the return value (or exception) back to the waiting thread.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot


class GuiCallTimeout(RuntimeError):
    """The GUI thread did not run or finish the call in time."""


class _Job:
    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.lock = threading.Lock()
        self.started = False
        self.cancelled = False
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class GuiThreadInvoker(QObject):
    """Create on the GUI thread; :meth:`call` may then be used from any thread."""

    _submit = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._submit.connect(self._run, Qt.QueuedConnection)

    def call(self, fn: Callable[[], Any], *, timeout_s: float = 5.0) -> Any:
        """
        Run ``fn()`` on the GUI thread and return its result (re-raises its exception).

        Raises :class:`GuiCallTimeout` if the GUI thread is busy for ``timeout_s``. A call that times
        out before it started is cancelled and never runs, so the caller knows nothing happened.
        """
        if QThread.currentThread() == self.thread():
            return fn()
        job = _Job(fn)
        self._submit.emit(job)
        if not job.done.wait(timeout_s):
            with job.lock:
                if not job.started:
                    job.cancelled = True
                    raise GuiCallTimeout(
                        f"GUI busy: call not started within {timeout_s:g} s (nothing was done)"
                    )
            # Already running on the GUI thread: give it the same time again to finish.
            if not job.done.wait(timeout_s):
                raise GuiCallTimeout(
                    f"GUI call still running after {2 * timeout_s:g} s (outcome unknown)"
                )
        if job.error is not None:
            # Break job -> error -> traceback -> this frame -> job: the cycle would keep the caller's
            # frames (e.g. the HEROS zenoh query) alive until GC, and zenoh only ends a reply
            # stream when the query is freed (the client then waits for its 10 s timeout).
            error, job.error = job.error, None
            try:
                raise error
            finally:
                del error
        return job.result

    @pyqtSlot(object)
    def _run(self, job: _Job) -> None:
        with job.lock:
            if job.cancelled:
                return
            job.started = True
        try:
            job.result = job.fn()
        except Exception as e:
            job.error = e
        finally:
            job.done.set()
