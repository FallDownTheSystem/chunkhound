"""Global configuration management for ChunkHound.

This module provides persistent global configuration that applies across
all ChunkHound invocations, independent of project-local configuration.

The global config is stored in an XDG-compliant location:
- Primary: $XDG_CONFIG_HOME/chunkhound/config.json (usually ~/.config/chunkhound/)
- Fallback: ~/.chunkhound/config.json (for systems without XDG support)

Global config settings have lower precedence than project-local config,
environment variables, and CLI arguments.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any


class GlobalConfig:
    """Thread-safe global configuration manager for ChunkHound.

    Manages persistent global settings stored in a JSON file. Settings here
    apply to all ChunkHound invocations but can be overridden by project-local
    config, environment variables, or CLI arguments.

    Attributes:
            config_path: Path to the global configuration file.

    Example:
            >>> config = GlobalConfig()
            >>> config.get_auto_indexing()
            True
            >>> config.set("auto_indexing", False)
            >>> config.get_auto_indexing()
            False
    """

    # Default values for global settings
    _DEFAULTS: dict[str, Any] = {
        "auto_indexing": True,
    }

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize global configuration.

        Args:
                config_path: Optional explicit path to config file. If not provided,
                        uses XDG-compliant path resolution.
        """
        self._lock = threading.RLock()
        self._config_path = config_path or self._resolve_config_path()
        self._data: dict[str, Any] = self._load()

    @staticmethod
    def _resolve_config_path() -> Path:
        """Resolve the global config file path using XDG Base Directory spec.

        Resolution order:
        1. $CHUNKHOUND_GLOBAL_CONFIG_PATH (if set - for testing and overrides)
        2. $XDG_CONFIG_HOME/chunkhound/config.json (if XDG_CONFIG_HOME is set)
        3. ~/.config/chunkhound/config.json (XDG default on Linux/macOS)
        4. ~/.chunkhound/config.json (fallback for Windows or legacy)

        Returns:
                Path to the global configuration file.
        """
        # Check explicit override (for testing and custom deployments)
        if global_config_path := os.getenv("CHUNKHOUND_GLOBAL_CONFIG_PATH"):
            return Path(global_config_path)

        # Check XDG_CONFIG_HOME environment variable
        if xdg_config := os.getenv("XDG_CONFIG_HOME"):
            return Path(xdg_config) / "chunkhound" / "config.json"

        # Use XDG default on Unix-like systems, fallback for Windows
        home = Path.home()
        # Use runtime check to avoid mypy literal type narrowing
        is_windows = sys.platform.startswith("win")
        if is_windows:
            # Windows: use %APPDATA% or fallback to ~/.chunkhound
            appdata = os.getenv("APPDATA")
            if appdata:
                return Path(appdata) / "chunkhound" / "config.json"
            return home / ".chunkhound" / "config.json"

        # Linux/macOS: use XDG default
        return home / ".config" / "chunkhound" / "config.json"

    @property
    def config_path(self) -> Path:
        """Get the path to the global configuration file."""
        return self._config_path

    def _load(self) -> dict[str, Any]:
        """Load configuration from disk.

        Returns:
                Dictionary of configuration values, or empty dict if file doesn't exist.
        """
        if not self._config_path.exists():
            return {}

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            # Don't print in MCP mode to avoid breaking JSON-RPC protocol
            if not os.environ.get("CHUNKHOUND_MCP_MODE"):
                print(
                    f"Warning: Failed to load global config from "
                    f"{self._config_path}: {e}",
                    file=sys.stderr,
                )
            return {}

    def _save(self) -> None:
        """Save configuration to disk.

        Creates parent directories if they don't exist.

        Raises:
                OSError: If the file cannot be written.
        """
        # Create parent directories if needed
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically via temp file to prevent corruption
        # Use unique suffix to avoid race conditions between processes
        temp_path = self._config_path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")  # Trailing newline for POSIX compliance

            # Atomic rename (works on Unix, best-effort on Windows)
            temp_path.replace(self._config_path)
        except OSError:
            # Clean up temp file on failure
            temp_path.unlink(missing_ok=True)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
                key: Configuration key to retrieve.
                default: Default value if key is not set. If None, uses the
                        class-level default for known keys.

        Returns:
                The configuration value, or default if not set.
        """
        with self._lock:
            if key in self._data:
                return self._data[key]

            # Use class-level default if available
            if default is None and key in self._DEFAULTS:
                return self._DEFAULTS[key]

            return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and persist to disk.

        Args:
                key: Configuration key to set.
                value: Value to store.

        Raises:
                OSError: If the configuration cannot be saved.
        """
        with self._lock:
            self._data[key] = value
            self._save()

    def delete(self, key: str) -> bool:
        """Delete a configuration value.

        Args:
                key: Configuration key to delete.

        Returns:
                True if the key was deleted, False if it didn't exist.

        Raises:
                OSError: If the configuration cannot be saved.
        """
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def get_all(self) -> dict[str, Any]:
        """Get all configuration values including defaults.

        Returns:
                Dictionary of all settings with defaults filled in.
        """
        with self._lock:
            # Start with defaults, override with actual values
            result = dict(self._DEFAULTS)
            result.update(self._data)
            return result

    def get_auto_indexing(self) -> bool:
        """Get the auto-indexing setting.

        Returns:
                True if auto-indexing is enabled (default), False otherwise.
        """
        value = self.get("auto_indexing")
        # Ensure boolean type even if config file has invalid value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        # Return default (always True)
        return True

    def set_auto_indexing(self, enabled: bool) -> None:
        """Set the auto-indexing setting.

        Args:
                enabled: Whether auto-indexing should be enabled.
        """
        self.set("auto_indexing", enabled)

    def reload(self) -> None:
        """Reload configuration from disk.

        Useful if the config file was modified externally.
        """
        with self._lock:
            self._data = self._load()

    def __repr__(self) -> str:
        """String representation of GlobalConfig."""
        auto_idx = self.get_auto_indexing()
        return f"GlobalConfig(path={self._config_path}, auto_indexing={auto_idx})"
