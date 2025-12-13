"""Status command module - displays health and statistics information."""

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from chunkhound.api.cli.utils import verify_database_exists
from chunkhound.core.config.config import Config
from chunkhound.core.config.embedding_factory import EmbeddingProviderFactory
from chunkhound.database_factory import create_services
from chunkhound.embeddings import EmbeddingManager
from chunkhound.registry import configure_registry
from chunkhound.version import __version__

from ..utils.rich_output import RichOutputFormatter


def _format_size(size_mb: float) -> str:
	"""Format size in MB to human-readable string."""
	if size_mb < 1:
		return f"{size_mb * 1024:.1f} KB"
	elif size_mb < 1024:
		return f"{size_mb:.2f} MB"
	else:
		return f"{size_mb / 1024:.2f} GB"


async def status_command(args: argparse.Namespace, config: Config) -> None:
	"""Execute the status command to show health and statistics.

	Args:
		args: Parsed command-line arguments
		config: Pre-validated configuration instance
	"""
	formatter = RichOutputFormatter(verbose=args.verbose)

	# Get database path from config
	db_path = config.database.path

	# Check if database exists
	db_exists = False
	try:
		verify_database_exists(config)
		db_exists = True
	except (ValueError, FileNotFoundError):
		pass

	# Initialize embedding manager
	embedding_manager = EmbeddingManager()
	embedding_providers: list[str] = []

	# Setup embedding provider if configured
	try:
		if config.embedding:
			provider = EmbeddingProviderFactory.create_provider(config.embedding)
			embedding_manager.register_provider(provider, set_default=True)
			embedding_providers = embedding_manager.list_providers()
	except ValueError as e:
		logger.debug(f"Embedding provider setup skipped: {e}")
	except Exception as e:
		logger.debug(f"Unexpected error setting up embedding provider: {e}")

	# Build status response
	status_data: dict = {
		"status": "healthy",
		"version": __version__,
		"database_path": str(db_path),
		"database_exists": db_exists,
		"database_connected": False,
		"embedding_providers": embedding_providers,
		"stats": None,
	}

	# Get stats if database exists
	if db_exists:
		try:
			configure_registry(config)
			services = create_services(
				db_path=db_path, config=config, embedding_manager=embedding_manager
			)
			status_data["database_connected"] = services.provider.is_connected

			# Get database statistics
			raw_stats = services.provider.get_stats()
			status_data["stats"] = {
				"total_files": raw_stats.get("files", 0),
				"total_chunks": raw_stats.get("chunks", 0),
				"total_embeddings": raw_stats.get("embeddings", 0),
				"database_size_mb": raw_stats.get("size_mb", 0),
				"total_providers": raw_stats.get("providers", 0),
			}
		except Exception as e:
			logger.debug(f"Failed to get database stats: {e}")
			status_data["status"] = "degraded"
			status_data["error"] = str(e)

	# Output as JSON if requested
	if args.json:
		print(json.dumps(status_data, indent=2))
		return

	# Pretty print status
	formatter.info(f"ChunkHound v{__version__}")
	print()

	# Health status
	status_color = "green" if status_data["status"] == "healthy" else "yellow"
	if formatter._terminal_compatible and formatter.console:
		from rich.panel import Panel
		from rich.table import Table

		# Create status table
		table = Table(show_header=False, box=None, padding=(0, 2))
		table.add_column("Key", style="cyan")
		table.add_column("Value")

		table.add_row("Status", f"[{status_color}]{status_data['status']}[/{status_color}]")
		table.add_row("Database Path", str(db_path))

		if db_exists:
			table.add_row("Database Connected", "[green]Yes[/green]" if status_data["database_connected"] else "[red]No[/red]")
		else:
			table.add_row("Database Exists", "[yellow]No (run 'chunkhound index' to create)[/yellow]")

		if embedding_providers:
			table.add_row("Embedding Providers", ", ".join(embedding_providers))
		else:
			table.add_row("Embedding Providers", "[dim]None configured[/dim]")

		formatter.console.print(Panel(table, title="Health", border_style="blue"))

		# Stats table if available
		if status_data["stats"]:
			stats = status_data["stats"]
			stats_table = Table(show_header=False, box=None, padding=(0, 2))
			stats_table.add_column("Metric", style="cyan")
			stats_table.add_column("Value", justify="right")

			stats_table.add_row("Indexed Files", f"{stats['total_files']:,}")
			stats_table.add_row("Code Chunks", f"{stats['total_chunks']:,}")
			stats_table.add_row("Embeddings", f"{stats['total_embeddings']:,}")
			stats_table.add_row("Database Size", _format_size(stats['database_size_mb']))

			if stats['total_embeddings'] > 0:
				coverage = (stats['total_embeddings'] / stats['total_chunks'] * 100) if stats['total_chunks'] > 0 else 0
				stats_table.add_row("Embedding Coverage", f"{coverage:.1f}%")

			formatter.console.print(Panel(stats_table, title="Statistics", border_style="green"))

		# Error if present
		if "error" in status_data:
			formatter.error(f"Error: {status_data['error']}")
	else:
		# Fallback plain text output
		print(f"Status: {status_data['status']}")
		print(f"Database Path: {db_path}")

		if db_exists:
			connected = "Yes" if status_data["database_connected"] else "No"
			print(f"Database Connected: {connected}")
		else:
			print("Database Exists: No (run 'chunkhound index' to create)")

		if embedding_providers:
			print(f"Embedding Providers: {', '.join(embedding_providers)}")
		else:
			print("Embedding Providers: None configured")

		if status_data["stats"]:
			stats = status_data["stats"]
			print()
			print("Statistics:")
			print(f"  Indexed Files: {stats['total_files']:,}")
			print(f"  Code Chunks: {stats['total_chunks']:,}")
			print(f"  Embeddings: {stats['total_embeddings']:,}")
			print(f"  Database Size: {_format_size(stats['database_size_mb'])}")

			if stats['total_embeddings'] > 0:
				coverage = (stats['total_embeddings'] / stats['total_chunks'] * 100) if stats['total_chunks'] > 0 else 0
				print(f"  Embedding Coverage: {coverage:.1f}%")

		if "error" in status_data:
			print(f"\nError: {status_data['error']}")


__all__: list[str] = ["status_command"]
