from bom_dashboard import handler
from bom_dashboard.app_config import BomDashboardConfig
from bom_dashboard.app_ui import BomDashboardUI


def test_dashboard_registers_widget_and_requests_install_fields() -> None:
    widget = BomDashboardUI(None, None, None).to_schema(resolve_config=False)["children"]["BomDashboard"]
    assert widget["scope"] == "BomDashboardWidget"
    assert widget["module"] == "./BomDashboardWidget"
    assert widget["app_key"] == "$config.app().APP_KEY"

    permissions = BomDashboardConfig.to_schema()["properties"]["dv_proc_extended_permissions"]
    # The widget finds each device's BOM install through these.
    assert {"app_installs__name", "app_installs__application_name"} <= set(permissions["x-extraDeviceFields"])
    assert handler
