import builtins
import json
import os
import sys
import time
from typing import Any, Dict, List

import numpy

from heros import LocalHERO

from sequencer_gui.process_identity import HERO_INSTANCE_NAME, PROCESS_DISPLAY_NAME, SOFTWARE_PID
from sequencer_gui.domain.analog_stored import HOLD_SIGNAL
from sequencer_gui.sequence_io import sequence_model_from_hero_block

# DDS: ``AnalogParameterSpec.param_id`` in JSON ``device_rows[…]["frequency"]`` (Detuning MHz).
_DDS_FREQUENCY_PARAM = "frequency"


class Sequencer_HERO(LocalHERO):
    """
    JSON snapshot is stored in ``_sequence_data``. The instance also keeps a ``dict`` attribute
    pointing at the **same** mapping — :mod:`heros` :file:`capabilities.py` expects this for
    ``LocalHERO`` objects. Exposed methods only read via :meth:`_sequence_snapshot`.

    **Init order:** :class:`heros.heros.LocalHERO` runs :meth:`_capabilities` inside
    :meth:`heros.heros.LocalHERO.__init__` *before* any code in this class that runs after
    :keyword:`super`. Bind ``_sequence_data`` and ``dict`` **before** :keyword:`super` so
    ``getattr(self, \"dict\")`` during capability registration cannot fail.

    The integer pair ``(`` :attr:`_param_rev` ``,`` :attr:`_param_acked_rev` ``)`` lets a second
    process know whether the JSON snapshot (the same one returned by
    :meth:`export_sequence_data` / read via the ``get_seq_*`` helpers) is still the one it last
    fully applied: see :meth:`get_seq_parameters_stale` and :meth:`ack_seq_parameters_reloaded`.

    Integer parameters and return values: use quoted annotations such as ``"numpy.int32"`` in
    source and ``numpy.int32(...)`` at runtime. Plain ``int`` and ARTIQ host ``TInt32`` are
    unsuitable. Use the **Petanque** :mod:`heros` build (``numpy`` in :mod:`heros.heros` globals,
    ``type_to_str`` for numpy types as ``numpy.int32``, etc.); see ``requirements-artiq.txt`` for
    the editable install line.
    """

    def __init__(self, name: str, *args, **kwargs):
        d: Dict[str, Any] = {}
        object.__setattr__(self, "_sequence_data", d)
        # Same id as _sequence_data; heros _capabilities may getattr(self, "dict") before post-super code runs.
        object.__setattr__(self, "dict", d)
        super().__init__(name, *args, **kwargs)
        # GUI Pause/Resume; not part of ``set_sequence_data`` / saved JSON.
        object.__setattr__(self, "_run_sequence", True)
        object.__setattr__(self, "_param_rev", 0)
        # ``-1`` never matches any post-increment rev so the consumer sees "stale" until first ack.
        object.__setattr__(self, "_param_acked_rev", -1)
        # Optional developer convenience: preload an initial JSON snapshot if explicitly requested.
        # IMPORTANT: do not hardcode a path here; it can cause confusing "random" block counts when
        # multiple HERO servers exist or when the GUI has not yet pushed its document.
        init_path = os.environ.get("SEQUENCER_HERO_INIT_JSON")
        if init_path:
            try:
                if os.path.isfile(init_path):
                    self.load_json_file(init_path)
            except Exception:
                # Best-effort: the GUI will immediately push the authoritative document.
                pass

    def _sequence_snapshot(self) -> Dict[str, Any]:
        """Live JSON-shaped mapping; use this from all heros-exposed methods."""
        try:
            return self._sequence_data
        except AttributeError:
            d: Dict[str, Any] = {}
            object.__setattr__(self, "_sequence_data", d)
            object.__setattr__(self, "dict", d)
            return d

    def set_sequence_data(self, data: Dict[str, Any]) -> None:
        """Replace the in-memory sequence (GUI calls this; same shape as a ``.json`` file)."""
        pr = int(getattr(self, "_param_rev", 0)) + 1
        object.__setattr__(self, "_param_rev", pr)
        object.__setattr__(self, "_sequence_data", data)
        object.__setattr__(self, "dict", data)

    def load_json_file(self, file_path: str) -> None:
        with open(file_path, "r") as file:
            self.set_sequence_data(json.load(file))

    def get_n_blocks(self) -> "numpy.int32":
        """Number of sequence blocks in the current document (GUI rows are separate)."""
        return numpy.int32(
            len(self._sequence_snapshot().get("document", {}).get("blocks", []))
        )

    def get_n_columns(self, block_index: "numpy.int32") -> "numpy.int32":
        """Time slots for this block. Prefer the ``cols`` field; else ``len(delays_us)``."""
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        if "cols" in block:
            return numpy.int32(block["cols"])
        return numpy.int32(len(block.get("delays_us", [])))

    def is_block_enabled(self, block_index: "numpy.int32") -> bool:
        if block_index < 0 or block_index >= self.get_n_blocks():
            return False
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        if "enabled" not in block:
            return True
        return bool(block["enabled"])

    def get_total_nb_steps(self) -> "numpy.int32":
        """
        Number of time slots in the flattened timeline (enabled blocks only, in block order);
        the value to use as ``length`` for :meth:`get_seq_float_list` / :meth:`get_seq_bool_list`
        when you want the full sequence with no padding.
        """
        total = 0
        n_blocks = int(self.get_n_blocks())
        for b in range(n_blocks):
            if not self.is_block_enabled(numpy.int32(b)):
                continue
            total += int(self.get_n_columns(numpy.int32(b)))
        return numpy.int32(total)

    def get_row_index_by_label(self, label: str) -> "numpy.int32":
        """
        Return the device row index for a label in ``document['row_labels']``,
        or -1 if missing.
        """
        try:
            labels: list = self._sequence_snapshot()["document"]["row_labels"]
            return numpy.int32(labels.index(label))
        except (ValueError, KeyError, TypeError, AttributeError):
            return numpy.int32(-1)

    def get_shutter_img_row(self) -> "numpy.int32":
        """Row index for ``Shutter_IMG``; defaults to 1 (legacy hardcoded) if not found."""
        r = self.get_row_index_by_label("Shutter_IMG")
        if r < 0:
            return numpy.int32(1)
        return numpy.int32(r)

    def get_trigger_camera_row(self) -> "numpy.int32":
        """Row index for ``Trigger Camera``; defaults to 2 (legacy hardcoded) if not found."""
        r = self.get_row_index_by_label("Trigger Camera")
        if r < 0:
            return numpy.int32(2)
        return numpy.int32(r)

    def get_seq_parameters_stale(self) -> bool:
        """
        ``True`` if the in-memory sequence snapshot was replaced since the last
        :meth:`ack_seq_parameters_reloaded` (e.g. the external program should re-read
        :meth:`export_sequence_data` or the various ``get_seq_*`` / ``get_*`` accessors).
        """
        return int(getattr(self, "_param_rev", 0)) != int(getattr(self, "_param_acked_rev", -1))

    def ack_seq_parameters_reloaded(self) -> None:
        """
        Mark the current snapshot as fully consumed by the external program (sets "last time" to
        the active revision; :meth:`get_seq_parameters_stale` becomes false until the next
        :meth:`set_sequence_data` / file load).
        """
        object.__setattr__(
            self, "_param_acked_rev", int(getattr(self, "_param_rev", 0))
        )

    def export_sequence_data(self) -> Dict[str, Any]:
        """Shallow copy of the live snapshot (avoids a method name ending in ``get_dict`` for heros)."""
        m = self._sequence_snapshot()
        return builtins.dict(m)

    @staticmethod
    def _coerce_seq_analog_float(value: Any) -> float:
        """JSON cell: number, the string ``hold``, or ``null``; ``hold`` and ``null`` both become :data:`HOLD_SIGNAL`."""
        if value == "hold":
            return HOLD_SIGNAL
        if value is None:
            return HOLD_SIGNAL
        return float(value)

    def get_seq_float(
        self,
        block_index: int,
        time_slot_index: int,
        param: str,
        device_index: int = 0,
    ) -> float:
        """
        Per-step float from ``device_rows`` for one analog list key (e.g. ``frequency`` for
        detuning MHz, ``current``). The alias ``detuning`` maps to ``frequency``.

        If the value is null or the string hold, a row or key is missing, the index is out of
        range, or the JSON shape is wrong, returns :data:`HOLD_SIGNAL` (also for values that are
        not coercible to a float).

        For the block delay column in µs, use :meth:`get_seq_delay_us` (not stored on a device row).
        """
        p = (param or "").strip().lower()
        if not p:
            raise ValueError("param must be a non-empty string")
        row_key = _DDS_FREQUENCY_PARAM if p == "detuning" else p
        try:
            block = self._sequence_snapshot()["document"]["blocks"][block_index]
            device_rows = block["device_rows"]
            row = device_rows[str(int(device_index))]
        except (KeyError, IndexError, TypeError):
            return HOLD_SIGNAL
        if row_key not in row or row[row_key] is None:
            return HOLD_SIGNAL
        col = row[row_key]
        try:
            if time_slot_index < 0 or time_slot_index >= len(col):
                return HOLD_SIGNAL
            v = col[time_slot_index]
        except (TypeError, KeyError, IndexError):
            return HOLD_SIGNAL
        try:
            return self._coerce_seq_analog_float(v)
        except (TypeError, ValueError, OverflowError):
            return HOLD_SIGNAL

    def get_seq_float_list(
        self,
        param: str,
        length: int,
        device_index: int = 0,
    ) -> List[float]:
        """
        ``length``-element analog timeline: same block/column order as a kernel ``offset`` loop
        (``param`` / ``device_index`` as :meth:`get_seq_float`). The result is **always** ``len ==
        length``: excess steps in the document are **truncated**; if the sequence is shorter, the
        tail is padded with :data:`HOLD_SIGNAL` (``null`` / hold semantics for unused table slots).
        For per-column block delays, use :meth:`get_seq_delay_list`.
        """
        if length < 0:
            raise ValueError("length must be non-negative")
        if length == 0:
            return []
        out: List[float] = []
        n_blocks = int(self.get_n_blocks())
        for b in range(n_blocks):
            if not self.is_block_enabled(numpy.int32(b)):
                continue
            n = int(self.get_n_columns(numpy.int32(b)))
            for i in range(n):
                if len(out) == length:
                    return out
                out.append(self.get_seq_float(b, i, param, device_index))
        while len(out) < length:
            out.append(HOLD_SIGNAL)
        return out

    def get_seq_delay_list(
        self,
        length: int,
        fill_extra_delay_us: float = 1.0,
    ) -> List[float]:
        """
        ``length``-element ``delays_us`` timeline: same order as :meth:`get_seq_float_list` for a
        row. **Always** ``len == length``: long sequences are **truncated**; short ones are **padded**
        with ``fill_extra_delay_us`` (default ``1.0`` µs, a neutral one-microsecond step).
        """
        if length < 0:
            raise ValueError("length must be non-negative")
        if length == 0:
            return []
        out: List[float] = []
        n_blocks = int(self.get_n_blocks())
        for b in range(n_blocks):
            if not self.is_block_enabled(numpy.int32(b)):
                continue
            n = int(self.get_n_columns(numpy.int32(b)))
            for i in range(n):
                if len(out) == length:
                    return out
                out.append(self.get_seq_delay_us(b, i))
        while len(out) < length:
            out.append(float(fill_extra_delay_us))
        return out

    def get_seq_delay_us(self, block_index: int, time_slot_index: int) -> float:
        return float(
            self._sequence_snapshot()["document"]["blocks"][block_index]["delays_us"][
                time_slot_index
            ]
        )

    def get_seq_bool(self, block_index: int, time_slot_index: int, device_index: int) -> bool:
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        return bool(block["device_rows"][str(int(device_index))]["states"][time_slot_index])

    def get_seq_bool_list(
        self,
        length: int,
        device_index: int = 0,
    ) -> List[bool]:
        """
        ``length``-element digital timeline: same block/column order as :meth:`get_seq_float_list`
        (``device_index`` selects the device row). The result is **always** ``len == length``:
        excess steps are **truncated**; if the sequence is shorter, the tail is padded with
        ``False``; invalid or out-of-range cells are treated as ``False``.
        """
        if length < 0:
            raise ValueError("length must be non-negative")
        if length == 0:
            return []
        out: List[bool] = []
        n_blocks = int(self.get_n_blocks())
        for b in range(n_blocks):
            if not self.is_block_enabled(numpy.int32(b)):
                continue
            n = int(self.get_n_columns(numpy.int32(b)))
            for i in range(n):
                if len(out) == length:
                    return out
                try:
                    out.append(self.get_seq_bool(b, i, device_index))
                except (KeyError, IndexError, TypeError, AttributeError):
                    out.append(False)
        while len(out) < length:
            out.append(False)
        return out

    def get_seq_detuning(
        self, block_index: int, time_slot_index: int, device_index: int = 0
    ) -> float:
        return self.get_seq_float(
            block_index, time_slot_index, _DDS_FREQUENCY_PARAM, device_index
        )

    def set_run_sequence(self, on: bool) -> None:
        """Set from the GUI only; independent of the JSON snapshot."""
        object.__setattr__(self, "_run_sequence", bool(on))

    def get_run_sequence(self) -> bool:
        """True = run allowed; false = paused (see :meth:`set_run_sequence`)."""
        return bool(getattr(self, "_run_sequence", True))


if __name__ == "__main__":
    if "SEQUENCER_SOFTWARE_PID" not in os.environ:
        os.environ["SEQUENCER_SOFTWARE_PID"] = str(SOFTWARE_PID)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(PROCESS_DISPLAY_NAME)
        except Exception:
            pass
    elif sys.stdout.isatty():
        sys.stdout.write(f"\033]0;{PROCESS_DISPLAY_NAME}\007")
        sys.stdout.flush()

    # Avoid name collisions with the GUI (which also runs a HERO named HERO_INSTANCE_NAME).
    # If both are running and share the same name, clients may hit either server.
    standalone_name = os.environ.get("SEQUENCER_HERO_NAME", f"{HERO_INSTANCE_NAME}_standalone")
    with Sequencer_HERO(standalone_name) as sequencer_hero:
        while True:
            time.sleep(1)
