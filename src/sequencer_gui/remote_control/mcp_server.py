"""MCP server giving AI agents read access to the running Sequencer GUI.

The agent's client (e.g. Claude Code) starts this process and talks to it over stdio. Each tool
call opens a :class:`heros.RemoteHERO` to ``Sequencer_Control_HERO`` in the GUI, so the server
keeps no state and survives GUI restarts. Phase 1: read-only tools.

Run (normally started by the MCP client, not by hand)::

    venv_sequencer\\Scripts\\python.exe -m sequencer_gui.remote_control.mcp_server

``SEQUENCER_CONTROL_HERO_NAME`` overrides the HERO name (tests).
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from sequencer_gui.process_identity import CONTROL_HERO_INSTANCE_NAME
from sequencer_gui.remote_control.agent_views import (
    format_devices,
    format_overview,
    format_timeline,
)

HERO_NAME = os.environ.get("SEQUENCER_CONTROL_HERO_NAME", CONTROL_HERO_INSTANCE_NAME)

INSTRUCTIONS = """\
Read access to the Petanque Sequencer GUI (ARTIQ experiment sequences for an Rb-87 tweezer
experiment). The tools show the sequence currently open in the GUI; they cannot change it.

Sequence model:
- Timeline rows are devices (AOM, DDS, shutter, TTL, current source, ...), addressed by label.
- The sequence is a list of blocks; only enabled blocks are played, concatenated in order
  (the "Complete" timeline). Each column (timestep) has a delay in microseconds.
- Analog values are stored only where they change; every other column holds the previous value.
  "ramp" (AOM / piezo only) ramps to the next value. Parameter labels carry the units.
- Static devices hold one value per shot, applied between shots.
- Every reply carries a revision id that changes whenever the sequence changes.

Start with sequencer_overview, then sequencer_timeline (Complete view or one block) and
sequencer_devices for parameter ranges.
"""

server = MCPServer(name="sequencer", instructions=INSTRUCTIONS)

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


class _ToolError(Exception):
    """Message returned to the agent as the tool result."""


def _call(method: str, *args: Any) -> Any:
    """Call the GUI's control HERO and unwrap its ``{"ok", "result" | "error"}`` envelope."""
    try:
        from heros import RemoteHERO
    except ImportError as e:
        raise _ToolError(f"heros is not installed in this Python ({e})") from e
    try:
        with RemoteHERO(HERO_NAME) as hero:
            raw = getattr(hero, method)(*args)
    except Exception as e:
        raise _ToolError(
            f"Cannot reach {HERO_NAME} ({type(e).__name__}: {e}). Is the Sequencer GUI running, "
            "and was it started after the remote control API was added?"
        ) from e
    reply = json.loads(raw)
    if not reply.get("ok"):
        raise _ToolError(str(reply.get("error", "unknown error")))
    return reply["result"]


def _text(build) -> str:
    try:
        return build()
    except (_ToolError, ValueError) as e:
        return f"Error: {e}"


@server.tool(annotations=_READ_ONLY)
def sequencer_overview() -> str:
    """Sequence name, revision, blocks (enabled, columns, duration), cycle rate, run and scan state."""
    return _text(lambda: format_overview(_call("get_overview")))


@server.tool(annotations=_READ_ONLY)
def sequencer_devices() -> str:
    """All timeline rows and static devices with device type, parameters, units and ranges."""
    return _text(lambda: format_devices(_call("get_devices")))


@server.tool(annotations=_READ_ONLY)
def sequencer_timeline(
    block: str = "", rows: list[str] | None = None, include_unused: bool = False
) -> str:
    """Timeline as compact text: column labels and delays, ON ranges, stored analog values.

    Args:
        block: block name or 0-based index; empty = Complete timeline (enabled blocks as played).
        rows: only these rows (labels or indices); default = all rows that are used.
        include_unused: also list rows that are never ON and store no value.
    """

    def build() -> str:
        data = _call("get_block", block) if block.strip() else _call("get_complete_timeline")
        return format_timeline(data, rows=rows, include_unused=include_unused)

    return _text(build)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
