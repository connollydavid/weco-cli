"""Execution mode: local (the default) or weco (the explicit cloud opt-in).

Local mode never talks to Weco endpoints: no login, no credits, no event
reporting, no installation identifier, no update pings. Cloud features are
reached only by opting in with ``WECO_MODE=weco`` (or the ``--mode weco``
flag where a command accepts one), which restores upstream behavior
unchanged.
"""

from __future__ import annotations

import os

LOCAL = "local"
WECO = "weco"

_VALID = (LOCAL, WECO)


class ModeError(ValueError):
    """Raised when WECO_MODE holds a value that names no mode."""


def resolve_mode(env: dict[str, str] | None = None) -> str:
    """Resolve the execution mode from the environment (default: local)."""
    source = env if env is not None else os.environ
    value = (source.get("WECO_MODE") or "").strip().lower()
    if value == "":
        return LOCAL
    if value in _VALID:
        return value
    raise ModeError(f"WECO_MODE must be one of {', '.join(_VALID)} (got {value!r})")


def is_local(env: dict[str, str] | None = None) -> bool:
    """True when running in local mode (the default)."""
    try:
        return resolve_mode(env) == LOCAL
    except ModeError:
        # An invalid mode value should not silently flip the telemetry gates
        # back on; treat it as local and let the explicit resolvers complain.
        return True
