"""The org's WaterNSW subscription, and which BoM Station devices it feeds."""

from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig, ScheduleConfig

from .api import DEFAULT_URL


class WaterNswConfig(config.Schema):
    subscription_key = config.String(
        "Subscription Key",
        default="",
        description=(
            "The key from your WaterNSW API developer portal profile "
            "(api-portal.waternsw.com.au), subscribed to the Water Data product."
        ),
    )
    # Grant "Apps Installed: BoM Station" so every gauge in the org is fed. Each
    # device's BoM Station install is found by its application name.
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=["id", "name", "display_name", "app_installs__name", "app_installs__application_name"]
    )
    url = config.String("Service URL", default=DEFAULT_URL, advanced=True)
    # Hourly keeps up to 20 gauges inside the Basic tier's 29 requests a day.
    schedule = ScheduleConfig(
        allowed_modes=["rate", "cron"], default="rate(1 hour)", advanced=True
    )
    position = config.ApplicationPosition()


def export() -> None:
    WaterNswConfig.export(Path(__file__).parents[2] / "doover_config.json", "waternsw_integration")
