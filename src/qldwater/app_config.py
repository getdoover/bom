"""Which BoM Station devices the Queensland portal feeds, and how often."""

from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig, ScheduleConfig

from .api import DEFAULT_URL


class QldWaterConfig(config.Schema):
    # Grant "Apps Installed: BoM Station" so every gauge in the org is fed. Each
    # device's BoM Station install is found by its application name.
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=["id", "name", "display_name", "app_installs__name", "app_installs__application_name"]
    )
    url = config.String("Service URL", default=DEFAULT_URL, advanced=True)
    # Gauges transmit on the hour; the department asks for one call an hour,
    # at half past.
    schedule = ScheduleConfig(
        allowed_modes=["rate", "cron"], default="cron(30 * * * ?)", advanced=True
    )
    position = config.ApplicationPosition()


def export() -> None:
    QldWaterConfig.export(Path(__file__).parents[2] / "doover_config.json", "qldwater_integration")
