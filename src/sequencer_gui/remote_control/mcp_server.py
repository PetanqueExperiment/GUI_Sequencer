"""MCP server giving AI agents read access to the running Sequencer GUI.

The agent's client (e.g. Claude Code) starts this process and talks to it over stdio. Each tool
call opens a :class:`heros.RemoteHERO` to ``Sequencer_Control_HERO`` in the GUI, so the server
keeps no state and survives GUI restarts. Read tools, plus proposals that the operator approves
in the GUI (the server itself never changes the sequence).

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

Changing the sequence or setting up a scan: call sequencer_propose. It opens an approval window
in the GUI; nothing changes until the operator accepts. The operator may accept only some changes,
and decides the scan separately (an accepted scan goes into the Scan panel; the operator starts it).
Use the revision from sequencer_overview as base_revision; if the operator edited the sequence
since, the proposal is refused: re-read and propose again. Only one proposal can wait at a time.
After proposing, tell the operator to check the window, and call sequencer_proposal_status when
they say they decided (do not poll repeatedly).
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


_PROPOSE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _status_text(st: dict[str, Any]) -> str:
    lines = [f"Proposal {st['proposal_id']}: "
             + ("still waiting for the operator" if st["waiting_for_operator"] else "decided")]
    if "changes" in st:
        c = st["changes"]
        lines.append(f"  changes: {c['status']}")
        if c["accepted"]:
            lines.append(f"    applied: {', '.join(c['accepted'])}")
        if c["status"] != "pending" and c["not_accepted"]:
            lines.append(f"    not applied: {', '.join(c['not_accepted'])}")
    if "scan" in st:
        s = st["scan"]
        lines.append(f"  scan \"{s['label']}\": {s['status']}" + (f" ({s['note']})" if "note" in s else ""))
    return "\n".join(lines)


@server.tool(annotations=_PROPOSE)
def sequencer_propose(
    summary: str,
    base_revision: str,
    changes: list[dict[str, Any]] | None = None,
    scan: dict[str, Any] | None = None,
) -> str:
    """Propose sequence changes and/or a scan; opens an approval window in the GUI.

    Nothing is applied until the operator accepts. Columns are on the Complete timeline: a column
    label, or cN / N (0-based). Values are in the units of the parameter label.

    Args:
        summary: one short line for the operator (what and why).
        base_revision: revision from sequencer_overview that the proposal is based on.
        changes: list of edits, each one of
            {"row": <row label>, "param": <param_id>, "column": <col>, "value": <number | "hold" | "ramp">}
            {"row": <row label>, "column": <col>, "on": true | false}
            {"column": <col>, "delay_us": <number>}
        scan: {"label": <PyCam experiment name>, "repetitions": <int>, "reason": <why>,
               "axes": [{"device": <row label | static device | "time">, "param": <param_id>,
                         "timestep": <col>, "values": [<numbers>]}]}
            For a delay axis use device "time" and param "time".
    """

    def build() -> str:
        data: dict[str, Any] = {"summary": summary, "base_revision": base_revision}
        if changes:
            data["changes"] = changes
        if scan:
            data["scan"] = scan
        reply = _call("submit_proposal", json.dumps(data))
        return (f"Proposal {reply['proposal_id']} is shown to the operator in the approval window. "
                "Nothing is applied until they accept. Ask them to check it, then call "
                "sequencer_proposal_status with this id once they have decided.")

    return _text(build)


@server.tool(annotations=_READ_ONLY)
def sequencer_proposal_status(proposal_id: str) -> str:
    """What the operator decided on a proposal: changes and scan, each pending / accepted / rejected /
    undone / dismissed (window closed), with the changes actually applied."""
    return _text(lambda: _status_text(_call("get_proposal_status", proposal_id)))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
