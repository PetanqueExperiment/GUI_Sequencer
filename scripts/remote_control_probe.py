"""Call the read-only remote control API of a running Sequencer GUI and print the replies.

Usage (from the repo root, with the sequencer venv)::

    venv_sequencer\\Scripts\\python.exe scripts\\remote_control_probe.py
    venv_sequencer\\Scripts\\python.exe scripts\\remote_control_probe.py --block "Block 1"
"""

from __future__ import annotations

import argparse
import json

from heros import RemoteHERO

DEFAULT_NAME = "Sequencer_Control_HERO"  # sequencer_gui.process_identity.CONTROL_HERO_INSTANCE_NAME


def probe(name: str, block: str | None) -> list[tuple[str, dict]]:
    with RemoteHERO(name) as hero:
        replies = [
            ("get_overview", json.loads(hero.get_overview())),
            ("get_devices", json.loads(hero.get_devices())),
            ("get_complete_timeline", json.loads(hero.get_complete_timeline())),
        ]
        if block is not None:
            replies.append((f"get_block({block!r})", json.loads(hero.get_block(block))))
    return replies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_NAME, help="HERO name of the control API")
    parser.add_argument("--block", default=None, help="also fetch this block (name or index)")
    args = parser.parse_args()
    for method, reply in probe(args.name, args.block):
        text = json.dumps(reply, indent=1)
        print(f"--- {method} ({len(text)} chars)")
        print(text if len(text) < 3000 else text[:3000] + "\n...")


if __name__ == "__main__":
    main()
