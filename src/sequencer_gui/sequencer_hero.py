import json
import os
import sys
import time

from heros import LocalHERO

FILE_NAME = os.path.basename(__file__)


class Sequencer_HERO(LocalHERO):
    """
    Exposes sequence data via ``self.dict`` (same top-level keys as a saved ``.json`` file:
    ``format``, ``version``, ``name``, ``document``).

    The GUI injects :class:`sequencer_gui.app.hero_dict_backend.HeroDictBackend` so ``dict`` stays in sync.
    """

    def __init__(self, name: str, *args, **kwargs):
        super().__init__(name, *args, **kwargs)
        self.dict = {}
        self.load_json_file(r"C:\Users\PETANQUE-PC\Desktop\Tom\sequencer_test.json")

    def load_json_file(self, file_path: str) -> None:
        with open(file_path, "r") as file:
            self.dict = json.load(file)

    def get_float(self, key: str) -> float:
        return float(self.dict[key])

    def get_bool(self, key: str) -> bool:
        return bool(self.dict[key])

    def get_n_blocks(self) -> int:
        """Number of sequence blocks in the current document (GUI rows are separate)."""
        return len(self.dict.get("document", {}).get("blocks", []))

    def get_n_rows(self) -> int:
        """Number of device rows in the matrix (e.g. AOM, shutter, TTL, …)."""
        return int(self.dict.get("document", {}).get("rows", 0))

    def get_n_columns(self, block_index: int) -> int:
        """Time slots for this block. Prefer the ``cols`` field; else ``len(delays_us)``."""
        block = self.dict["document"]["blocks"][block_index]
        if "cols" in block:
            return int(block["cols"])
        return len(block.get("delays_us", []))

    def is_block_enabled(self, block_index: int) -> bool:
        if block_index < 0 or block_index >= self.get_n_blocks():
            return False
        block = self.dict["document"]["blocks"][block_index]
        if "enabled" not in block:
            return True
        return bool(block["enabled"])

    def get_row_index_by_label(self, label: str) -> int:
        """
        Return the device row index for a label in ``document['row_labels']``,
        or -1 if missing.
        """
        try:
            labels: list = self.dict["document"]["row_labels"]
            return int(labels.index(label))
        except (ValueError, KeyError, TypeError, AttributeError):
            return -1

    def get_shutter_img_row(self) -> int:
        """Row index for ``Shutter_IMG``; defaults to 1 (legacy hardcoded) if not found."""
        r = self.get_row_index_by_label("Shutter_IMG")
        if r < 0:
            return 1
        return r

    def get_trigger_camera_row(self) -> int:
        """Row index for ``Trigger Camera``; defaults to 2 (legacy hardcoded) if not found."""
        r = self.get_row_index_by_label("Trigger Camera")
        if r < 0:
            return 2
        return r

    def get_bool_from_json_file(
        self, block_index: int, device_index: int, time_slot_index: int
    ) -> bool:
        return bool(
            self.dict["document"]["blocks"][block_index]["channels"][device_index][time_slot_index]
        )

    def get_delays_us_from_json_file(self, block_index: int, time_slot_index: int) -> float:
        return float(self.dict["document"]["blocks"][block_index]["delays_us"][time_slot_index])

    def get_dict(self) -> dict:
        return dict(self.dict)


if __name__ == "__main__":
    if sys.stdout.isatty():
        sys.stdout.write(f"\033]0;{FILE_NAME}\007")
        sys.stdout.flush()

    name = "Sequencer_HERO"

    with Sequencer_HERO(name) as sequencer_hero:
        while True:
            time.sleep(1)
