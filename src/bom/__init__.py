"""AWS Lambda entry point for the BOM water gauge processor."""

from typing import Any

from pydoover.processor import run_app

from .application import Bom


def handler(event: dict[str, Any], context: Any) -> None:
    run_app(Bom(), event, context)
