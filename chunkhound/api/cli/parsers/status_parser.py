"""Status command argument parser for ChunkHound CLI."""

import argparse
from pathlib import Path
from typing import Any, cast

from .common_arguments import add_common_arguments, add_config_arguments


def add_status_subparser(subparsers: Any) -> argparse.ArgumentParser:
	"""Add status command subparser to the main parser.

	Args:
		subparsers: Subparsers object from the main argument parser

	Returns:
		The configured status subparser
	"""
	status_parser = subparsers.add_parser(
		"status",
		help="Show database status and health information",
		description="Display health check and statistics for the ChunkHound index",
	)

	# Optional positional argument with default to current directory
	status_parser.add_argument(
		"path",
		nargs="?",
		type=Path,
		default=Path("."),
		help="Directory path to check status for (default: current directory)",
	)

	# Output format
	status_parser.add_argument(
		"--json",
		action="store_true",
		help="Output status as JSON",
	)

	# Add common arguments
	add_common_arguments(status_parser)

	# Add config-specific arguments - only database needed for status
	add_config_arguments(status_parser, ["database"])

	return cast(argparse.ArgumentParser, status_parser)


__all__: list[str] = ["add_status_subparser"]
