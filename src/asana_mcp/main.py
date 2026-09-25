import logging
import sys

from asana_mcp.registry import mcp

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

from asana_mcp import tools  # noqa: F401, E402


def run() -> None:
    """Запускает MCP-сервер в stdio-режиме."""
    mcp.run(transport="stdio")
