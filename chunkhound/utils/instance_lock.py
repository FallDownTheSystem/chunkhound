"""Instance lock mechanism for ChunkHound MCP servers.

This module provides per-project instance locking to prevent multiple MCP servers
from running with auto-indexing enabled for the same project. Lock files are
stored in ~/.chunkhound/locks/ with filenames based on the hash of the project path.

Lock files contain JSON with PID, start time, and project path for debugging.
Stale locks (from crashed processes) are automatically detected and overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _is_process_running(pid: int) -> bool:
	"""Check if a process with the given PID is running.

	This is a cross-platform implementation that handles both Unix and Windows.

	Args:
		pid: Process ID to check.

	Returns:
		True if the process is running, False otherwise.
	"""
	if pid <= 0:
		return False

	if sys.platform == "win32":
		# Windows: Use kernel32.OpenProcess to check if process exists
		try:
			import ctypes

			PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
			SYNCHRONIZE = 0x00100000

			# Try to open the process with minimal permissions
			handle = ctypes.windll.kernel32.OpenProcess(
				PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
			)
			if handle:
				ctypes.windll.kernel32.CloseHandle(handle)
				return True
			return False
		except (AttributeError, OSError):
			# Fallback: assume process is running if we can't check
			return True
	else:
		# Unix: Use os.kill with signal 0 (doesn't actually send signal)
		try:
			os.kill(pid, 0)
			return True
		except OSError:
			return False


def _get_lock_path_for_project(project_path: Path) -> Path:
	"""Get the lock file path for a given project.

	Lock files are stored in ~/.chunkhound/locks/ with filenames based on
	a SHA256 hash (truncated to 16 chars) of the absolute project path.

	Args:
		project_path: Path to the project directory.

	Returns:
		Path to the lock file for this project.
	"""
	# Use absolute path for consistent hashing
	abs_path = str(project_path.resolve())
	path_hash = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]

	# Store locks in ~/.chunkhound/locks/
	locks_dir = Path.home() / ".chunkhound" / "locks"
	return locks_dir / f"{path_hash}.lock"


class InstanceLock:
	"""Per-project instance lock for ChunkHound MCP servers.

	This lock ensures only one MCP server instance with auto-indexing enabled
	can run for a given project at a time. Multiple projects can run simultaneously,
	and multiple servers can run for the same project if auto-indexing is disabled.

	Lock files contain JSON metadata for debugging:
	- pid: Process ID of the lock holder
	- start_time: ISO timestamp when the lock was acquired
	- project_path: Absolute path to the project (for debugging)
	- transport: MCP transport type (stdio/http) if available

	Stale locks from crashed processes are automatically detected by checking
	if the recorded PID is still running.

	Attributes:
		lock_path: Path to the lock file.
		project_path: Path to the project being locked.

	Example:
		>>> lock = InstanceLock(project_path=Path("/path/to/project"))
		>>> if lock.acquire():
		...     try:
		...         # Do work
		...         pass
		...     finally:
		...         lock.release()
		... else:
		...     print("Another instance is already running")
	"""

	def __init__(
		self,
		project_path: Path,
		lock_path: Path | None = None,
		transport: str | None = None,
	) -> None:
		"""Initialize the instance lock.

		Args:
			project_path: Path to the project directory.
			lock_path: Optional explicit lock file path. If not provided,
				uses the default location based on project path hash.
			transport: Optional transport type (stdio/http) for lock metadata.
		"""
		self._project_path = project_path.resolve()
		self._lock_path = lock_path or _get_lock_path_for_project(project_path)
		self._transport = transport
		self._acquired = False

	@property
	def lock_path(self) -> Path:
		"""Get the path to the lock file."""
		return self._lock_path

	@property
	def project_path(self) -> Path:
		"""Get the path to the project being locked."""
		return self._project_path

	@property
	def is_acquired(self) -> bool:
		"""Check if this instance currently holds the lock."""
		return self._acquired

	def _read_lock_file(self) -> dict[str, Any] | None:
		"""Read and parse the lock file.

		Returns:
			Lock file contents as dict, or None if file doesn't exist or is invalid.
		"""
		if not self._lock_path.exists():
			return None

		try:
			with open(self._lock_path, encoding="utf-8") as f:
				data = json.load(f)
				return data if isinstance(data, dict) else None
		except (json.JSONDecodeError, OSError):
			return None

	def _write_lock_file(self, exclusive: bool = False) -> None:
		"""Write the lock file with current process information.

		Creates parent directories if needed.

		Args:
			exclusive: If True, use exclusive creation mode ('x') which fails
				if file already exists. This prevents race conditions.

		Raises:
			FileExistsError: If exclusive=True and lock file already exists.
			OSError: If lock file cannot be written.
		"""
		# Create locks directory
		self._lock_path.parent.mkdir(parents=True, exist_ok=True)

		# Build lock metadata
		lock_data = {
			"pid": os.getpid(),
			"start_time": datetime.now(timezone.utc).isoformat(),
			"project_path": str(self._project_path),
		}
		if self._transport:
			lock_data["transport"] = self._transport

		# Write lock file
		# Use 'x' mode for atomic creation (fails if file exists)
		# Use 'w' mode when overwriting stale locks
		mode = "x" if exclusive else "w"
		with open(self._lock_path, mode, encoding="utf-8") as f:
			json.dump(lock_data, f, indent=2)
			f.write("\n")

	def _is_lock_stale(self, lock_data: dict[str, Any]) -> bool:
		"""Check if an existing lock is stale (holder process no longer running).

		Args:
			lock_data: Contents of the lock file.

		Returns:
			True if the lock is stale and can be overwritten, False otherwise.
		"""
		pid = lock_data.get("pid")
		if not isinstance(pid, int):
			# Invalid lock file format - treat as stale
			return True

		return not _is_process_running(pid)

	def acquire(self, _retry_count: int = 0) -> bool:
		"""Attempt to acquire the lock.

		Uses atomic file creation to prevent race conditions between multiple
		processes trying to acquire the lock simultaneously. If a lock file
		exists, checks if the holding process is still running. Stale locks
		from crashed processes are automatically removed and re-acquired.

		Args:
			_retry_count: Internal counter to prevent infinite recursion.

		Returns:
			True if lock was acquired, False if another instance is running.

		Raises:
			OSError: If lock file cannot be read or written.
		"""
		if self._acquired:
			return True

		# Prevent infinite recursion in edge cases
		if _retry_count > 3:
			return False

		# Ensure parent directory exists
		self._lock_path.parent.mkdir(parents=True, exist_ok=True)

		try:
			# Try atomic creation - fails if file already exists
			self._write_lock_file(exclusive=True)
			self._acquired = True
			return True
		except FileExistsError:
			# Lock file exists - check if it's stale
			existing_lock = self._read_lock_file()

			if existing_lock is None:
				# File exists but couldn't be read (corrupted/empty)
				# Try to remove and retry
				try:
					self._lock_path.unlink()
					return self.acquire(_retry_count + 1)
				except FileNotFoundError:
					# Someone else removed it, try again
					return self.acquire(_retry_count + 1)
				except OSError:
					# Couldn't remove (permissions?), assume locked
					return False

			if not self._is_lock_stale(existing_lock):
				# Another instance is actively running
				return False

			# Stale lock - try to remove and re-acquire
			try:
				self._lock_path.unlink()
				return self.acquire(_retry_count + 1)
			except FileNotFoundError:
				# Someone else already removed it, try again
				return self.acquire(_retry_count + 1)
			except OSError:
				# Couldn't remove stale lock (permissions?), assume locked
				return False

	def release(self) -> None:
		"""Release the lock and remove the lock file.

		Safe to call multiple times. Only removes the lock file if this
		instance actually holds the lock.
		"""
		if not self._acquired:
			return

		try:
			# Verify we still own the lock before removing
			existing_lock = self._read_lock_file()
			if existing_lock and existing_lock.get("pid") == os.getpid():
				self._lock_path.unlink(missing_ok=True)
		except OSError:
			pass  # Best effort cleanup

		self._acquired = False

	def get_lock_info(self) -> dict[str, Any] | None:
		"""Get information about the current lock holder.

		Returns:
			Lock metadata dict if lock file exists, None otherwise.
		"""
		return self._read_lock_file()

	def __enter__(self) -> InstanceLock:
		"""Context manager entry - acquire the lock.

		Raises:
			RuntimeError: If lock cannot be acquired.
		"""
		if not self.acquire():
			lock_info = self.get_lock_info()
			pid = lock_info.get("pid", "unknown") if lock_info else "unknown"
			raise RuntimeError(
				f"Another ChunkHound MCP server is already running for "
				f"{self._project_path} (PID {pid}). "
				f"Only one instance with auto-indexing enabled is allowed per project."
			)
		return self

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
		"""Context manager exit - release the lock."""
		self.release()

	def __repr__(self) -> str:
		"""String representation of InstanceLock."""
		status = "acquired" if self._acquired else "not acquired"
		return f"InstanceLock(project={self._project_path}, status={status})"
