"""Tests for InstanceLock class.

This module tests the instance locking mechanism for MCP servers,
including cross-platform PID checking, lock acquisition, and stale lock detection.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from chunkhound.utils.instance_lock import (
	InstanceLock,
	_get_lock_path_for_project,
	_is_process_running,
)


@pytest.fixture
def temp_locks_dir(tmp_path: Path) -> Path:
	"""Create a temporary locks directory."""
	locks_dir = tmp_path / "locks"
	locks_dir.mkdir(parents=True, exist_ok=True)
	return locks_dir


@pytest.fixture
def temp_project_path(tmp_path: Path) -> Path:
	"""Create a temporary project directory."""
	project_dir = tmp_path / "test_project"
	project_dir.mkdir(parents=True, exist_ok=True)
	return project_dir


@pytest.fixture
def instance_lock(temp_locks_dir: Path, temp_project_path: Path) -> InstanceLock:
	"""Create an InstanceLock with temporary paths."""
	lock_path = temp_locks_dir / "test.lock"
	return InstanceLock(project_path=temp_project_path, lock_path=lock_path)


class TestIsProcessRunning:
	"""Tests for the _is_process_running function."""

	def test_current_process_is_running(self) -> None:
		"""Current process should be detected as running."""
		assert _is_process_running(os.getpid()) is True

	def test_invalid_pid_zero(self) -> None:
		"""PID 0 should return False."""
		assert _is_process_running(0) is False

	def test_invalid_pid_negative(self) -> None:
		"""Negative PIDs should return False."""
		assert _is_process_running(-1) is False

	def test_nonexistent_pid(self) -> None:
		"""Non-existent PID should return False."""
		# Use a very high PID that's unlikely to exist
		# Max PID is usually 32768 on Linux, 4194304 on newer kernels
		# Windows max is higher but this should still be unlikely to exist
		assert _is_process_running(4194303) is False


class TestGetLockPathForProject:
	"""Tests for lock path generation."""

	def test_generates_consistent_path(self, tmp_path: Path) -> None:
		"""Same project path should generate same lock path."""
		project = tmp_path / "my_project"
		project.mkdir()

		path1 = _get_lock_path_for_project(project)
		path2 = _get_lock_path_for_project(project)

		assert path1 == path2

	def test_different_projects_different_paths(self, tmp_path: Path) -> None:
		"""Different project paths should generate different lock paths."""
		project1 = tmp_path / "project1"
		project2 = tmp_path / "project2"
		project1.mkdir()
		project2.mkdir()

		path1 = _get_lock_path_for_project(project1)
		path2 = _get_lock_path_for_project(project2)

		assert path1 != path2

	def test_path_uses_hash_prefix(self, tmp_path: Path) -> None:
		"""Lock path should use hash-based filename."""
		project = tmp_path / "test_project"
		project.mkdir()

		lock_path = _get_lock_path_for_project(project)

		# Should be 16 hex chars + .lock extension
		assert lock_path.suffix == ".lock"
		assert len(lock_path.stem) == 16
		# Verify it's a valid hex string
		int(lock_path.stem, 16)

	def test_path_in_home_chunkhound_locks(self, tmp_path: Path) -> None:
		"""Lock path should be in ~/.chunkhound/locks/."""
		project = tmp_path / "test_project"
		project.mkdir()

		lock_path = _get_lock_path_for_project(project)

		expected_parent = Path.home() / ".chunkhound" / "locks"
		assert lock_path.parent == expected_parent


class TestInstanceLockBasicOperations:
	"""Tests for basic lock operations."""

	def test_acquire_lock_success(self, instance_lock: InstanceLock) -> None:
		"""Should successfully acquire lock when no lock exists."""
		assert instance_lock.acquire() is True
		assert instance_lock.is_acquired is True

	def test_acquire_creates_lock_file(self, instance_lock: InstanceLock) -> None:
		"""Acquiring lock should create the lock file."""
		instance_lock.acquire()
		assert instance_lock.lock_path.exists()

	def test_lock_file_contains_pid(self, instance_lock: InstanceLock) -> None:
		"""Lock file should contain current PID."""
		instance_lock.acquire()

		with open(instance_lock.lock_path) as f:
			data = json.load(f)

		assert data["pid"] == os.getpid()

	def test_lock_file_contains_project_path(
		self, instance_lock: InstanceLock, temp_project_path: Path
	) -> None:
		"""Lock file should contain project path."""
		instance_lock.acquire()

		with open(instance_lock.lock_path) as f:
			data = json.load(f)

		assert data["project_path"] == str(temp_project_path.resolve())

	def test_lock_file_contains_timestamp(self, instance_lock: InstanceLock) -> None:
		"""Lock file should contain start timestamp."""
		instance_lock.acquire()

		with open(instance_lock.lock_path) as f:
			data = json.load(f)

		assert "start_time" in data
		# Should be ISO format
		assert "T" in data["start_time"]

	def test_lock_file_contains_transport_when_provided(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Lock file should contain transport type when provided."""
		lock = InstanceLock(
			project_path=temp_project_path,
			lock_path=temp_locks_dir / "test.lock",
			transport="stdio",
		)
		lock.acquire()

		with open(lock.lock_path) as f:
			data = json.load(f)

		assert data["transport"] == "stdio"

	def test_release_removes_lock_file(self, instance_lock: InstanceLock) -> None:
		"""Releasing lock should remove the lock file."""
		instance_lock.acquire()
		assert instance_lock.lock_path.exists()

		instance_lock.release()
		assert not instance_lock.lock_path.exists()
		assert instance_lock.is_acquired is False

	def test_release_is_idempotent(self, instance_lock: InstanceLock) -> None:
		"""Releasing multiple times should be safe."""
		instance_lock.acquire()
		instance_lock.release()
		instance_lock.release()  # Should not raise
		instance_lock.release()  # Should not raise

	def test_acquire_is_idempotent(self, instance_lock: InstanceLock) -> None:
		"""Acquiring multiple times when already holding lock should succeed."""
		assert instance_lock.acquire() is True
		assert instance_lock.acquire() is True
		assert instance_lock.is_acquired is True


class TestInstanceLockConflicts:
	"""Tests for lock conflict handling."""

	def test_acquire_fails_when_lock_exists_same_process(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Acquiring should fail when another active lock exists (same project)."""
		lock1 = InstanceLock(
			project_path=temp_project_path,
			lock_path=temp_locks_dir / "test.lock",
		)
		lock2 = InstanceLock(
			project_path=temp_project_path,
			lock_path=temp_locks_dir / "test.lock",
		)

		assert lock1.acquire() is True

		# Second lock should fail (same process holds it)
		assert lock2.acquire() is False

	def test_different_projects_can_acquire_simultaneously(
		self, temp_locks_dir: Path, tmp_path: Path
	) -> None:
		"""Different projects should be able to hold locks simultaneously."""
		project1 = tmp_path / "project1"
		project2 = tmp_path / "project2"
		project1.mkdir()
		project2.mkdir()

		lock1 = InstanceLock(
			project_path=project1,
			lock_path=temp_locks_dir / "lock1.lock",
		)
		lock2 = InstanceLock(
			project_path=project2,
			lock_path=temp_locks_dir / "lock2.lock",
		)

		assert lock1.acquire() is True
		assert lock2.acquire() is True


class TestStaleLockDetection:
	"""Tests for stale lock detection and cleanup."""

	def test_stale_lock_from_nonexistent_pid(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should detect and overwrite locks from non-existent PIDs."""
		lock_path = temp_locks_dir / "test.lock"

		# Create a lock file with a non-existent PID
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		with open(lock_path, "w") as f:
			json.dump(
				{
					"pid": 4194303,  # Very unlikely to be a real process
					"start_time": "2025-01-01T00:00:00+00:00",
					"project_path": str(temp_project_path),
				},
				f,
			)

		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		assert lock.acquire() is True  # Should succeed by overwriting stale lock

	def test_invalid_lock_file_format(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should treat invalid lock file format as stale."""
		lock_path = temp_locks_dir / "test.lock"

		# Create a lock file with invalid format
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		with open(lock_path, "w") as f:
			json.dump({"invalid": "format"}, f)  # Missing PID

		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		assert lock.acquire() is True

	def test_non_dict_lock_file(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should treat non-dict lock file as stale."""
		lock_path = temp_locks_dir / "test.lock"

		# Create a lock file with array instead of object
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		with open(lock_path, "w") as f:
			json.dump(["not", "a", "dict"], f)

		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		assert lock.acquire() is True

	def test_invalid_json_lock_file(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should treat invalid JSON lock file as no lock."""
		lock_path = temp_locks_dir / "test.lock"

		# Create a lock file with invalid JSON
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		with open(lock_path, "w") as f:
			f.write("not valid json {{{")

		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		assert lock.acquire() is True

	def test_active_lock_not_overwritten(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should not overwrite lock from active process."""
		lock_path = temp_locks_dir / "test.lock"

		# Create a lock file with current PID (simulating active process)
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		with open(lock_path, "w") as f:
			json.dump(
				{
					"pid": os.getpid(),  # Current process
					"start_time": "2025-01-01T00:00:00+00:00",
					"project_path": str(temp_project_path),
				},
				f,
			)

		# Different lock instance should fail to acquire
		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		# This tests the "same process" case which should fail
		assert lock.acquire() is False


class TestContextManager:
	"""Tests for context manager interface."""

	def test_context_manager_acquires_on_enter(
		self, instance_lock: InstanceLock
	) -> None:
		"""Context manager should acquire lock on enter."""
		with instance_lock:
			assert instance_lock.is_acquired is True
			assert instance_lock.lock_path.exists()

	def test_context_manager_releases_on_exit(
		self, instance_lock: InstanceLock
	) -> None:
		"""Context manager should release lock on exit."""
		with instance_lock:
			pass

		assert instance_lock.is_acquired is False
		assert not instance_lock.lock_path.exists()

	def test_context_manager_releases_on_exception(
		self, instance_lock: InstanceLock
	) -> None:
		"""Context manager should release lock even on exception."""
		with pytest.raises(ValueError):
			with instance_lock:
				raise ValueError("test error")

		assert instance_lock.is_acquired is False
		assert not instance_lock.lock_path.exists()

	def test_context_manager_raises_on_conflict(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Context manager should raise RuntimeError on conflict."""
		lock1 = InstanceLock(
			project_path=temp_project_path,
			lock_path=temp_locks_dir / "test.lock",
		)
		lock2 = InstanceLock(
			project_path=temp_project_path,
			lock_path=temp_locks_dir / "test.lock",
		)

		with lock1:
			with pytest.raises(RuntimeError) as exc_info:
				with lock2:
					pass

		assert "already running" in str(exc_info.value)
		assert str(temp_project_path.resolve()) in str(exc_info.value)


class TestGetLockInfo:
	"""Tests for get_lock_info method."""

	def test_get_lock_info_returns_none_when_no_lock(
		self, instance_lock: InstanceLock
	) -> None:
		"""Should return None when no lock file exists."""
		assert instance_lock.get_lock_info() is None

	def test_get_lock_info_returns_lock_data(
		self, instance_lock: InstanceLock
	) -> None:
		"""Should return lock data when lock exists."""
		instance_lock.acquire()
		info = instance_lock.get_lock_info()

		assert info is not None
		assert info["pid"] == os.getpid()
		assert "start_time" in info


class TestRepr:
	"""Tests for string representation."""

	def test_repr_includes_project_path(
		self, instance_lock: InstanceLock, temp_project_path: Path
	) -> None:
		"""Repr should include project path."""
		repr_str = repr(instance_lock)
		assert str(temp_project_path.resolve()) in repr_str

	def test_repr_shows_status(self, instance_lock: InstanceLock) -> None:
		"""Repr should show acquisition status."""
		repr_str = repr(instance_lock)
		assert "not acquired" in repr_str

		instance_lock.acquire()
		repr_str = repr(instance_lock)
		assert "acquired" in repr_str
		assert "not acquired" not in repr_str


class TestDirectoryCreation:
	"""Tests for automatic directory creation."""

	def test_creates_parent_directories(self, tmp_path: Path) -> None:
		"""Should create parent directories when acquiring lock."""
		project = tmp_path / "project"
		project.mkdir()
		lock_path = tmp_path / "deep" / "nested" / "locks" / "test.lock"

		lock = InstanceLock(project_path=project, lock_path=lock_path)
		lock.acquire()

		assert lock_path.exists()
		assert lock_path.parent.exists()


class TestReleaseVerification:
	"""Tests for release verification."""

	def test_release_verifies_ownership(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Release should only remove lock if we still own it."""
		lock_path = temp_locks_dir / "test.lock"
		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		lock.acquire()

		# Simulate another process overwriting our lock
		with open(lock_path, "w") as f:
			json.dump(
				{
					"pid": 99999,  # Different PID
					"start_time": "2025-01-01T00:00:00+00:00",
					"project_path": str(temp_project_path),
				},
				f,
			)

		# Release should NOT remove the lock file since we don't own it anymore
		lock.release()
		assert lock_path.exists()


class TestAtomicAcquisition:
	"""Tests for atomic lock acquisition pattern."""

	def test_acquire_uses_exclusive_creation(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""First acquisition should use exclusive file creation."""
		lock_path = temp_locks_dir / "test.lock"
		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)

		# Should succeed with atomic creation
		assert lock.acquire() is True
		assert lock_path.exists()

	def test_acquire_handles_corrupted_lock_file(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Should handle corrupted (empty) lock files by removing and retrying."""
		lock_path = temp_locks_dir / "test.lock"

		# Create an empty (corrupted) lock file
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		lock_path.write_text("")

		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		# Should remove corrupted file and acquire successfully
		assert lock.acquire() is True

	def test_acquire_retry_limit_prevents_infinite_loop(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Retry limit should prevent infinite recursion."""
		lock_path = temp_locks_dir / "test.lock"
		lock = InstanceLock(project_path=temp_project_path, lock_path=lock_path)

		# Calling with high retry count should fail immediately
		assert lock.acquire(_retry_count=10) is False

	def test_second_lock_fails_with_active_process(
		self, temp_locks_dir: Path, temp_project_path: Path
	) -> None:
		"""Second lock attempt should fail when first lock is active."""
		lock_path = temp_locks_dir / "test.lock"
		lock1 = InstanceLock(project_path=temp_project_path, lock_path=lock_path)
		lock2 = InstanceLock(project_path=temp_project_path, lock_path=lock_path)

		assert lock1.acquire() is True
		# Second lock should fail because first lock is held by running process
		assert lock2.acquire() is False
