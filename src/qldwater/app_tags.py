"""What the last fetch did, and where the next one starts from."""

from pydoover import tags


class QldWaterTags(tags.Tags):
    status = tags.String(default=None)
    gauges = tags.Number(default=None)  # devices fed on the last run
    readings = tags.Number(default=None)  # points fetched on the last run
    # When the last fully successful fetch started (ms since epoch); the next
    # asks for everything logged since, less an overlap for late telemetry.
    fetched_at = tags.Number(default=None)
