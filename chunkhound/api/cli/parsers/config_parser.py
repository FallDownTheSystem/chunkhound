"""Config command argument parser for ChunkHound CLI."""

import argparse
from typing import Any, cast


def add_config_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Add config command subparser to the main parser.

    The config command manages global ChunkHound configuration that persists
    across sessions. Currently supports:
    - auto_indexing: Enable/disable automatic background indexing on MCP server startup

    Args:
            subparsers: Subparsers object from the main argument parser

    Returns:
            The configured config subparser
    """
    config_parser = subparsers.add_parser(
        "config",
        help="Manage global ChunkHound configuration",
        description=(
            "Manage global ChunkHound settings that persist across sessions. "
            "Global settings apply to all ChunkHound commands but can be overridden "
            "by project-local config, environment variables, or CLI arguments."
        ),
    )

    # Add config subcommands
    config_subparsers = config_parser.add_subparsers(
        dest="config_subcommand",
        help="Configuration subcommands",
    )

    # config get <key>
    get_parser = config_subparsers.add_parser(
        "get",
        help="Get a configuration value",
        description="Display the current value of a global configuration setting.",
    )
    get_parser.add_argument(
        "key",
        help="Configuration key to retrieve (e.g., auto_indexing)",
    )

    # config set <key> <value>
    set_parser = config_subparsers.add_parser(
        "set",
        help="Set a configuration value",
        description=(
            "Set a global configuration value. Changes take effect for new processes."
        ),
    )
    set_parser.add_argument(
        "key",
        help="Configuration key to set (e.g., auto_indexing)",
    )
    set_parser.add_argument(
        "value",
        help="Value to set (e.g., true, false for booleans)",
    )

    # config list
    config_subparsers.add_parser(
        "list",
        help="List all configuration values",
        description=(
            "Display all global configuration settings and their current values."
        ),
    )

    return cast(argparse.ArgumentParser, config_parser)


__all__: list[str] = ["add_config_subparser"]
