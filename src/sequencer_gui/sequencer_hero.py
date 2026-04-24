import builtins
import json
import os
import sys
import time
from typing import Any, Dict

import numpy

from heros import LocalHERO

from sequencer_gui.process_identity import HERO_INSTANCE_NAME, PROCESS_DISPLAY_NAME, SOFTWARE_PID
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
        self.load_json_file(r"C:\Users\PETANQUE-PC\Desktop\Tom\sequencer_test.json")

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
        object.__setattr__(self, "_sequence_data", data)
        object.__setattr__(self, "dict", data)

    def load_json_file(self, file_path: str) -> None:
        with open(file_path, "r") as file:
            self.set_sequence_data(json.load(file))

    def get_float(self, key: str) -> float:
        return float(self._sequence_snapshot()[key])

    def get_bool(self, key: str) -> bool:
        return bool(self._sequence_snapshot()[key])

    def get_n_blocks(self) -> "numpy.int32":
        """Number of sequence blocks in the current document (GUI rows are separate)."""
        return numpy.int32(
            len(self._sequence_snapshot().get("document", {}).get("blocks", []))
        )

    def get_n_rows(self) -> "numpy.int32":
        """Number of device rows in the matrix (e.g. AOM, shutter, TTL, …)."""
        return numpy.int32(
            self._sequence_snapshot().get("document", {}).get("rows", 0)
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

    def get_bool_from_json_file(
        self, block_index: int, device_index: int, time_slot_index: int
    ) -> bool:
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        return bool(block["device_rows"][str(int(device_index))]["states"][time_slot_index])

    def get_delays_us_from_json_file(self, block_index: int, time_slot_index: int) -> float:
        return float(self._sequence_snapshot()["document"]["blocks"][block_index]["delays_us"][time_slot_index])

    def export_sequence_data(self) -> Dict[str, Any]:
        """Shallow copy of the live snapshot (avoids a method name ending in ``get_dict`` for heros)."""
        m = self._sequence_snapshot()
        return builtins.dict(m)

    def get_seq_delay_us(self, block_index: int, time_slot_index: int) -> float:
        return float(self._sequence_snapshot()["document"]["blocks"][block_index]["delays_us"][time_slot_index])
    
    def get_seq_bool(self, block_index: int, time_slot_index: int, device_index: int) -> bool:
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        return bool(block["device_rows"][str(int(device_index))]["states"][time_slot_index])
    
    def get_seq_detuning(self, block_index: int, time_slot_index: int, device_index: int = 0) -> float:
        block = self._sequence_snapshot()["document"]["blocks"][block_index]
        value = block["device_rows"][str(int(device_index))]["frequency"][time_slot_index]
        return 0.0 if value is None else float(value)
   


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

    with Sequencer_HERO(HERO_INSTANCE_NAME) as sequencer_hero:
        while True:
            time.sleep(1)
