"""Mirror parameter changes pushed by remote static devices (HERO ``static_changed`` event)."""

from __future__ import annotations

import sys

from PyQt5.QtCore import QObject, pyqtSignal

# HERO event a static device emits with its current ``{param_id: value}`` whenever its
# state is updated on the device side (e.g. typed into the SLM Controller GUI).
STATIC_CHANGED_EVENT = "static_changed"


class StaticChangeListener(QObject):
    """
    Subscribes to ``static_changed`` from every HERO in the realm.

    Zenoh delivers events on its own threads; :attr:`values_received` is emitted from
    there, so connect it to a slot on a GUI-thread object (Qt queues it automatically).
    """

    values_received = pyqtSignal(str, object)  # hero_name, {param_id: value}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._observer = None
        try:
            from heros import EventObserver
        except ImportError as e:
            print(f"Static sync disabled (heros not installed: {e!r})", file=sys.stderr)
            return
        try:
            self._observer = EventObserver("*", STATIC_CHANGED_EVENT)
            self._observer.register_callback(self._on_event)
        except Exception as e:
            self._observer = None
            print(f"Static sync disabled ({e!r})", file=sys.stderr)

    def _on_event(self, hero_name: str, data: object) -> None:
        if isinstance(data, dict) and data:
            self.values_received.emit(str(hero_name), dict(data))

    def close(self) -> None:
        observer, self._observer = self._observer, None
        if observer is not None:
            try:
                observer.__exit__(None, None, None)
            except Exception:
                pass
