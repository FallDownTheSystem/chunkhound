"""Config command module - manages global ChunkHound configuration."""

import argparse
import sys

from chunkhound.core.config.global_config import GlobalConfig

from ..utils.rich_output import RichOutputFormatter


async def config_command(args: argparse.Namespace, config: object) -> None:
    """Execute the config command to manage global settings.

    The config command supports three subcommands:
    - get: Display a specific configuration value
    - set: Set a configuration value
    - list: Display all configuration values

    Args:
            args: Parsed command-line arguments
            config: Pre-validated configuration instance (unused for global config)
    """
    # Initialize Rich output formatter
    formatter = RichOutputFormatter(verbose=getattr(args, "verbose", False))

    # Load global configuration
    global_config = GlobalConfig()

    # Handle subcommand
    subcommand = getattr(args, "config_subcommand", None)

    if subcommand == "get":
        _handle_get(args, global_config, formatter)
    elif subcommand == "set":
        _handle_set(args, global_config, formatter)
    elif subcommand == "list":
        _handle_list(global_config, formatter)
    else:
        # No subcommand provided - show help
        formatter.error("No subcommand provided. Use: get, set, or list")
        formatter.info("\nExamples:")
        formatter.info("  chunkhound config list")
        formatter.info("  chunkhound config get auto_indexing")
        formatter.info("  chunkhound config set auto_indexing false")
        sys.exit(1)


def _handle_get(
    args: argparse.Namespace,
    global_config: GlobalConfig,
    formatter: RichOutputFormatter,
) -> None:
    """Handle the 'config get' subcommand.

    Args:
            args: Parsed command-line arguments (must have 'key' attribute)
            global_config: Global configuration instance
            formatter: Output formatter
    """
    key = args.key

    # Check if key is a known setting
    known_keys = list(GlobalConfig._DEFAULTS.keys())
    if key not in known_keys:
        formatter.warning(f"Unknown setting: {key}")
        formatter.info(f"Known settings: {', '.join(known_keys)}")
        sys.exit(1)

    value = global_config.get(key)
    formatter.info(f"{key} = {_format_value(value)}")


def _handle_set(
    args: argparse.Namespace,
    global_config: GlobalConfig,
    formatter: RichOutputFormatter,
) -> None:
    """Handle the 'config set' subcommand.

    Args:
            args: Parsed command-line arguments (must have 'key' and 'value' attributes)
            global_config: Global configuration instance
            formatter: Output formatter
    """
    key = args.key
    raw_value = args.value

    # Check if key is a known setting
    known_keys = list(GlobalConfig._DEFAULTS.keys())
    if key not in known_keys:
        formatter.warning(f"Unknown setting: {key}")
        formatter.info(f"Known settings: {', '.join(known_keys)}")
        sys.exit(1)

    # Parse value based on key type
    parsed_value = _parse_value(key, raw_value)
    if parsed_value is None:
        formatter.error(f"Invalid value for {key}: {raw_value}")
        formatter.info(f"Expected type: {_get_expected_type(key)}")
        sys.exit(1)

    # Set the value
    try:
        global_config.set(key, parsed_value)
        formatter.success(f"Set {key} = {_format_value(parsed_value)}")
        formatter.info(f"Config file: {global_config.config_path}")
    except OSError as e:
        formatter.error(f"Failed to save config: {e}")
        sys.exit(1)


def _handle_list(
    global_config: GlobalConfig,
    formatter: RichOutputFormatter,
) -> None:
    """Handle the 'config list' subcommand.

    Args:
            global_config: Global configuration instance
            formatter: Output formatter
    """
    formatter.section_header("ChunkHound Global Configuration")

    # Show config file location
    config_path = global_config.config_path
    if config_path.exists():
        formatter.info(f"Config file: {config_path}")
    else:
        formatter.info(f"Config file: {config_path} (not created yet)")

    formatter.info("")

    # List all settings with their current values
    all_settings = global_config.get_all()
    for key, value in sorted(all_settings.items()):
        default = GlobalConfig._DEFAULTS.get(key)
        is_default = value == default
        default_marker = " (default)" if is_default else ""
        formatter.info(f"  {key} = {_format_value(value)}{default_marker}")


def _format_value(value: object) -> str:
    """Format a configuration value for display.

    Args:
            value: Value to format

    Returns:
            Formatted string representation
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_value(key: str, raw_value: str) -> object | None:
    """Parse a raw string value into the appropriate type for the key.

    Args:
            key: Configuration key
            raw_value: Raw string value from CLI

    Returns:
            Parsed value or None if parsing failed
    """
    # Get default value to determine type
    default = GlobalConfig._DEFAULTS.get(key)

    if isinstance(default, bool):
        # Boolean parsing
        lower = raw_value.lower()
        if lower in ("true", "1", "yes", "on"):
            return True
        elif lower in ("false", "0", "no", "off"):
            return False
        else:
            return None

    if isinstance(default, int):
        try:
            return int(raw_value)
        except ValueError:
            return None

    if isinstance(default, float):
        try:
            return float(raw_value)
        except ValueError:
            return None

    # Default to string
    return raw_value


def _get_expected_type(key: str) -> str:
    """Get the expected type description for a configuration key.

    Args:
            key: Configuration key

    Returns:
            Type description string
    """
    default = GlobalConfig._DEFAULTS.get(key)

    if isinstance(default, bool):
        return "boolean (true/false)"
    if isinstance(default, int):
        return "integer"
    if isinstance(default, float):
        return "number"
    return "string"
