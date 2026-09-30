"""Which gauges the dashboard covers, and where it sits on the page."""

from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig


class BomDashboardConfig(config.Schema):
    # The widget finds each device's BoM Station install by its
    # application name, then reads that install's tags and history.
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=[
            "id",
            "name",
            "display_name",
            "group__name",
            "app_installs__name",
            "app_installs__application_name",
        ]
    )
    position = config.ApplicationPosition()


def export() -> None:
    BomDashboardConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "bom_dashboard"
    )
