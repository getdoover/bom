"""Device page UI: whether the integration is keeping up."""

from pathlib import Path

from pydoover import ui

from .app_tags import WaterNswTags as T


class WaterNswUI(ui.UI):
    status = ui.TextVariable("Status", value=T.status, icon="circle-info")
    gauges = ui.NumericVariable("Gauges Fed", value=T.gauges, precision=0, icon="water")
    readings = ui.NumericVariable("Readings Last Fetch", value=T.readings, precision=0, icon="list")
    fetched_at = ui.Timestamp("Last Fetch", value=T.fetched_at)


def export() -> None:
    WaterNswUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "waternsw_integration"
    )
