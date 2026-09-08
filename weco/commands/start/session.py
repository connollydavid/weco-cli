"""The dashboard session surface, offline-only.

The cloud relay (session creation, the realtime channel, heartbeats) is
gone with the cloud commands; the bridge runs offline, and this class is
the no-op surface the bridge publishes into.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

InboundHandler = Callable[[dict], Optional[Awaitable[None]]]


class DashboardSession:
    """An offline session: publishing is dropped, running is a no-op."""

    def __init__(self) -> None:
        self.dashboard_url: Optional[str] = None

    @classmethod
    def offline(cls) -> "DashboardSession":
        return cls()

    def publish(self, line: str) -> bool:
        return False

    async def run(self, *, on_inbound: InboundHandler, stop_event: asyncio.Event) -> None:
        return None
