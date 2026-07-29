"""Detect and apply static parameters on remote HERO devices."""

from __future__ import annotations

from dataclasses import dataclass


# Remote HERO method invoked by this GUI when committing a static parameter.
APPLY_STATIC_METHOD = "sequencer_apply_static"
DEFAULT_APPLY_ABS_TOL = 1e-6


@dataclass(frozen=True)
class DetectRowResult:
    row: int
    hero_name: str
    found: bool
    error: str | None = None


@dataclass(frozen=True)
class ApplyStaticResult:
    row: int
    param_id: str
    sent: float
    echoed: float | None
    ok: bool
    error: str | None = None


def values_match(
    sent: float, echoed: float, *, abs_tol: float = DEFAULT_APPLY_ABS_TOL
) -> bool:
    """True when ``|sent - echoed| <= abs_tol`` (equality at the tolerance is accepted)."""
    return abs(float(sent) - float(echoed)) <= float(abs_tol)


def detect_remote_hero(hero_name: str) -> tuple[bool, str | None]:
    """
    Try to reach a named HERO on the network.

    Returns ``(found, error_message)``. ``found`` is True only when the stub opens cleanly.
    """
    name = (hero_name or "").strip()
    if not name:
        return False, "Empty HERO name"
    try:
        from heros import RemoteHERO
    except ImportError as e:
        return False, f"HERO not installed ({e!r})"
    try:
        with RemoteHERO(name):
            return True, None
    except Exception as e:
        return False, str(e)


def apply_static_param(hero_name: str, param_id: str, value: float) -> float:
    """
    Call ``sequencer_apply_static(param_id, value)`` on the remote HERO; return the echoed applied value.

    Raises on connect / RPC failure. Callers compare the echo to ``value``.
    """
    name = (hero_name or "").strip()
    if not name:
        raise ValueError("Empty HERO name")
    pid = (param_id or "").strip()
    if not pid:
        raise ValueError("Empty param_id")
    from heros import RemoteHERO

    with RemoteHERO(name) as hero:
        method = getattr(hero, APPLY_STATIC_METHOD, None)
        if not callable(method):
            raise AttributeError(
                f"Remote HERO {name!r} has no {APPLY_STATIC_METHOD} method"
            )
        return float(method(pid, float(value)))


def apply_static_param_result(
    row: int,
    hero_name: str,
    param_id: str,
    value: float,
    *,
    abs_tol: float = DEFAULT_APPLY_ABS_TOL,
) -> ApplyStaticResult:
    """Same as :func:`apply_static_param` but always returns an :class:`ApplyStaticResult`."""
    try:
        echoed = apply_static_param(hero_name, param_id, value)
    except Exception as e:
        return ApplyStaticResult(
            row=row,
            param_id=param_id,
            sent=float(value),
            echoed=None,
            ok=False,
            error=str(e),
        )
    if not values_match(value, echoed, abs_tol=abs_tol):
        return ApplyStaticResult(
            row=row,
            param_id=param_id,
            sent=float(value),
            echoed=float(echoed),
            ok=False,
            error=f"Echo mismatch (sent {value}, got {echoed}, tol {abs_tol})",
        )
    return ApplyStaticResult(
        row=row,
        param_id=param_id,
        sent=float(value),
        echoed=float(echoed),
        ok=True,
        error=None,
    )


def push_document_static_to_remote(
    document: "SequenceDocument",
    row: int,
    param_id: str,
    value: float,
) -> ApplyStaticResult | None:
    """
    If ``row`` is a remote static device, call ``sequencer_apply_static``.

    Returns ``None`` for local-only rows; otherwise an :class:`ApplyStaticResult`.
    Echo tolerance comes from the static object class (``apply_abs_tol``).
    """
    from sequencer_gui.domain.document import SequenceDocument
    from sequencer_gui.software_objects.static.registry import apply_abs_tol_for

    if not isinstance(document, SequenceDocument):
        raise TypeError("document must be a SequenceDocument")
    if not document.static_is_remote(row):
        return None
    abs_tol = apply_abs_tol_for(document.static_software_name(row))
    return apply_static_param_result(
        row,
        document.static_hero_name(row),
        param_id,
        value,
        abs_tol=abs_tol,
    )
