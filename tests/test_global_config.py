"""Tests for GlobalConfig class.

This module tests the global configuration management functionality,
including XDG path resolution, thread-safe operations, and persistence.
"""

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from chunkhound.core.config.global_config import GlobalConfig


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for config testing."""
    config_dir = tmp_path / "chunkhound"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def temp_config_file(temp_config_dir: Path) -> Path:
    """Create a temporary config file path."""
    return temp_config_dir / "config.json"


@pytest.fixture
def global_config(temp_config_file: Path) -> GlobalConfig:
    """Create a GlobalConfig instance with a temporary config file."""
    return GlobalConfig(config_path=temp_config_file)


class TestPathResolution:
    """Tests for XDG-compliant config path resolution."""

    def test_respects_xdg_config_home(self, tmp_path: Path) -> None:
        """Should use XDG_CONFIG_HOME when set."""
        xdg_path = tmp_path / "xdg_config"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_path)}):
            resolved = GlobalConfig._resolve_config_path()
            assert resolved == xdg_path / "chunkhound" / "config.json"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_unix_default_path(self, tmp_path: Path) -> None:
        """On Unix without XDG_CONFIG_HOME, should use ~/.config/chunkhound."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove XDG_CONFIG_HOME if set
            env = dict(os.environ)
            env.pop("XDG_CONFIG_HOME", None)
            with patch.dict(os.environ, env, clear=True):
                with patch("pathlib.Path.home", return_value=tmp_path):
                    resolved = GlobalConfig._resolve_config_path()
                    assert (
                        resolved == tmp_path / ".config" / "chunkhound" / "config.json"
                    )

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_appdata_path(self, tmp_path: Path) -> None:
        """On Windows, should use APPDATA when set."""
        appdata_path = tmp_path / "AppData" / "Roaming"
        with patch.dict(os.environ, {"APPDATA": str(appdata_path)}, clear=False):
            # Remove XDG_CONFIG_HOME if set
            env = dict(os.environ)
            env.pop("XDG_CONFIG_HOME", None)
            env["APPDATA"] = str(appdata_path)
            with patch.dict(os.environ, env, clear=True):
                resolved = GlobalConfig._resolve_config_path()
                assert resolved == appdata_path / "chunkhound" / "config.json"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_fallback_path(self, tmp_path: Path) -> None:
        """On Windows without APPDATA, should use ~/.chunkhound."""
        env = dict(os.environ)
        env.pop("XDG_CONFIG_HOME", None)
        env.pop("APPDATA", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("pathlib.Path.home", return_value=tmp_path):
                resolved = GlobalConfig._resolve_config_path()
                assert resolved == tmp_path / ".chunkhound" / "config.json"


class TestBasicOperations:
    """Tests for basic get/set/delete operations."""

    def test_get_default_value(self, global_config: GlobalConfig) -> None:
        """Should return default value for unset keys."""
        assert global_config.get("nonexistent", "default") == "default"

    def test_get_class_default(self, global_config: GlobalConfig) -> None:
        """Should use class-level default for known keys."""
        # auto_indexing has a class-level default of True
        assert global_config.get("auto_indexing") is True

    def test_set_and_get(self, global_config: GlobalConfig) -> None:
        """Should persist and retrieve values."""
        global_config.set("test_key", "test_value")
        assert global_config.get("test_key") == "test_value"

    def test_set_persists_to_disk(
        self, global_config: GlobalConfig, temp_config_file: Path
    ) -> None:
        """Should write values to disk."""
        global_config.set("persistent_key", "persistent_value")

        # Verify file contents
        with open(temp_config_file) as f:
            data = json.load(f)
        assert data["persistent_key"] == "persistent_value"

    def test_delete_existing_key(self, global_config: GlobalConfig) -> None:
        """Should delete existing keys and return True."""
        global_config.set("to_delete", "value")
        result = global_config.delete("to_delete")
        assert result is True
        assert global_config.get("to_delete") is None

    def test_delete_nonexistent_key(self, global_config: GlobalConfig) -> None:
        """Should return False when deleting nonexistent key."""
        result = global_config.delete("nonexistent")
        assert result is False

    def test_get_all_includes_defaults(self, global_config: GlobalConfig) -> None:
        """Should include class-level defaults in get_all."""
        all_config = global_config.get_all()
        assert "auto_indexing" in all_config
        assert all_config["auto_indexing"] is True

    def test_get_all_includes_custom_values(self, global_config: GlobalConfig) -> None:
        """Should include custom values in get_all."""
        global_config.set("custom_key", "custom_value")
        all_config = global_config.get_all()
        assert all_config["custom_key"] == "custom_value"


class TestAutoIndexing:
    """Tests for auto-indexing specific methods."""

    def test_get_auto_indexing_default_true(self, global_config: GlobalConfig) -> None:
        """Auto-indexing should default to True."""
        assert global_config.get_auto_indexing() is True

    def test_set_auto_indexing_false(self, global_config: GlobalConfig) -> None:
        """Should be able to disable auto-indexing."""
        global_config.set_auto_indexing(False)
        assert global_config.get_auto_indexing() is False

    def test_set_auto_indexing_true(self, global_config: GlobalConfig) -> None:
        """Should be able to enable auto-indexing."""
        global_config.set_auto_indexing(False)
        global_config.set_auto_indexing(True)
        assert global_config.get_auto_indexing() is True

    def test_auto_indexing_persists(
        self, global_config: GlobalConfig, temp_config_file: Path
    ) -> None:
        """Auto-indexing setting should persist to disk."""
        global_config.set_auto_indexing(False)

        # Create new instance to verify persistence
        new_config = GlobalConfig(config_path=temp_config_file)
        assert new_config.get_auto_indexing() is False

    def test_auto_indexing_handles_string_true(self, temp_config_file: Path) -> None:
        """Should handle string 'true' as boolean True."""
        # Write string value directly to config file
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            json.dump({"auto_indexing": "true"}, f)

        config = GlobalConfig(config_path=temp_config_file)
        assert config.get_auto_indexing() is True

    def test_auto_indexing_handles_string_false(self, temp_config_file: Path) -> None:
        """Should handle string 'false' as boolean False."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            json.dump({"auto_indexing": "false"}, f)

        config = GlobalConfig(config_path=temp_config_file)
        assert config.get_auto_indexing() is False

    def test_auto_indexing_handles_string_yes(self, temp_config_file: Path) -> None:
        """Should handle string 'yes' as boolean True."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            json.dump({"auto_indexing": "yes"}, f)

        config = GlobalConfig(config_path=temp_config_file)
        assert config.get_auto_indexing() is True

    def test_auto_indexing_handles_invalid_value(self, temp_config_file: Path) -> None:
        """Should return default for invalid values."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            json.dump({"auto_indexing": 123}, f)

        config = GlobalConfig(config_path=temp_config_file)
        # Invalid type should return default (True)
        assert config.get_auto_indexing() is True


class TestFileOperations:
    """Tests for file I/O operations."""

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories when saving."""
        config_file = tmp_path / "deep" / "nested" / "config.json"
        config = GlobalConfig(config_path=config_file)
        config.set("key", "value")

        assert config_file.exists()
        assert config_file.parent.exists()

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        """Should work when config file doesn't exist."""
        config_file = tmp_path / "nonexistent" / "config.json"
        config = GlobalConfig(config_path=config_file)

        # Should use defaults
        assert config.get_auto_indexing() is True

    def test_handles_invalid_json(self, temp_config_file: Path) -> None:
        """Should handle invalid JSON gracefully."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            f.write("not valid json {{{")

        # Should not raise, should use empty config
        config = GlobalConfig(config_path=temp_config_file)
        assert config.get_auto_indexing() is True  # Default

    def test_handles_non_dict_json(self, temp_config_file: Path) -> None:
        """Should handle non-dict JSON gracefully."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            json.dump(["array", "not", "dict"], f)

        config = GlobalConfig(config_path=temp_config_file)
        assert config.get_auto_indexing() is True  # Default

    def test_reload_picks_up_external_changes(
        self, global_config: GlobalConfig, temp_config_file: Path
    ) -> None:
        """Should reload external changes on reload()."""
        global_config.set_auto_indexing(True)
        assert global_config.get_auto_indexing() is True

        # Modify file externally
        with open(temp_config_file, "w") as f:
            json.dump({"auto_indexing": False}, f)

        # Should still have old value
        assert global_config.get_auto_indexing() is True

        # After reload, should have new value
        global_config.reload()
        assert global_config.get_auto_indexing() is False


class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_reads(self, global_config: GlobalConfig) -> None:
        """Should handle concurrent reads safely."""
        global_config.set("shared_key", "shared_value")
        results = []

        def read_config():
            for _ in range(100):
                results.append(global_config.get("shared_key"))

        threads = [threading.Thread(target=read_config) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == "shared_value" for r in results)

    def test_concurrent_writes(
        self, global_config: GlobalConfig, temp_config_file: Path
    ) -> None:
        """Should handle concurrent writes safely."""
        errors = []

        def write_config(thread_id: int):
            try:
                for i in range(50):
                    global_config.set(f"key_{thread_id}", f"value_{i}")
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_config, i) for i in range(5)]
            for f in futures:
                f.result()

        assert len(errors) == 0

        # Verify file is still valid JSON
        with open(temp_config_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestRepr:
    """Tests for string representation."""

    def test_repr_includes_path(
        self, global_config: GlobalConfig, temp_config_file: Path
    ) -> None:
        """Repr should include config path."""
        repr_str = repr(global_config)
        assert str(temp_config_file) in repr_str

    def test_repr_includes_auto_indexing(self, global_config: GlobalConfig) -> None:
        """Repr should include auto_indexing state."""
        repr_str = repr(global_config)
        assert "auto_indexing=True" in repr_str

        global_config.set_auto_indexing(False)
        repr_str = repr(global_config)
        assert "auto_indexing=False" in repr_str


class TestMCPModeWarnings:
    """Tests for MCP mode behavior (no stderr output)."""

    def test_no_warnings_in_mcp_mode(
        self, temp_config_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should suppress warnings when CHUNKHOUND_MCP_MODE is set."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            f.write("invalid json {{{")

        with patch.dict(os.environ, {"CHUNKHOUND_MCP_MODE": "1"}):
            GlobalConfig(config_path=temp_config_file)

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warnings_without_mcp_mode(
        self, temp_config_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should show warnings when CHUNKHOUND_MCP_MODE is not set."""
        temp_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_config_file, "w") as f:
            f.write("invalid json {{{")

        # Ensure MCP mode is not set
        env = dict(os.environ)
        env.pop("CHUNKHOUND_MCP_MODE", None)
        with patch.dict(os.environ, env, clear=True):
            GlobalConfig(config_path=temp_config_file)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
