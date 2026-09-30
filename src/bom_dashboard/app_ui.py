"""Registers the dashboard widget in the device page UI."""

from pathlib import Path

from pydoover import ui


class BomDashboardUI(ui.UI, default_open=True):
    widget = ui.RemoteComponent(
        name="BomDashboard",
        display_name="River & Rain",
        component_url="$config.app().dv_widget_url",
        scope="BomDashboardWidget",
        module="./BomDashboardWidget",
        app_key="$config.app().APP_KEY",
    )


def export() -> None:
    BomDashboardUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "bom_dashboard"
    )
