"""Hosts the dashboard widget; all aggregation runs in the browser."""

from datetime import datetime, timezone

from pydoover.models import (
    ConnectionConfig,
    ConnectionDetermination,
    ConnectionStatus,
    ConnectionType,
    DeploymentEvent,
)
from pydoover.models.data.connection import ConnectionDisplay
from pydoover.processor import Application

from .app_config import BomDashboardConfig
from .app_ui import BomDashboardUI


class BomDashboard(Application):
    config_cls = BomDashboardConfig
    ui_cls = BomDashboardUI

    async def on_deployment(self, event: DeploymentEvent) -> None:
        # The dashboard has no data source of its own, so mark it online and
        # hide its connection status rather than letting it read as offline.
        await self.api.ping_connection_at(
            datetime.now(timezone.utc),
            ConnectionStatus.continuous_online_no_ping,
            ConnectionDetermination.online,
            user_agent="bom;dashboard",
        )
        await self.api.update_connection_config(
            ConnectionConfig(ConnectionType.periodic, display=ConnectionDisplay.never)
        )
