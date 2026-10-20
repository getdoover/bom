"""AWS Lambda entry point for the WaterNSW live data integration."""

from typing import Any

from pydoover.processor import run_app

from .application import WaterNsw


def handler(event: dict[str, Any], context: Any) -> None:
    run_app(WaterNsw(), event, context)
