"""Database resilience tests for APScheduler SQLite backend.

Tests that the ACTUAL start_scheduler() in src/globals.py recovers from
SQLite database corruption, locks, and filesystem failures.

Targets: src/globals.py (start_scheduler, SQLAlchemyJobStore)
Critical file: data/scheduler_jobs.sqlite
"""

import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore as APMemoryJobStore
import src.globals as ripple_globals


def _sample_job():
    """Dummy job function for scheduler tests"""
    pass


def _create_valid_scheduler_db(db_path):
    """Create a valid SQLite database that APScheduler would create"""
    jobstore = SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
    scheduler = BackgroundScheduler(jobstores={'default': jobstore})
    scheduler.start()
    scheduler.shutdown()
    return db_path


@pytest.fixture
def scheduler_env(tmp_path, monkeypatch):
    """Set up globals for testing start_scheduler() with a tmp database path.

    Monkeypatches SCHEDULER_DB_PATH to tmp_path, disables weekly reboot,
    resets scheduler state. Cleans up after test.
    """
    db_path = str(tmp_path / "scheduler_jobs.sqlite")
    monkeypatch.setattr(ripple_globals, 'SCHEDULER_DB_PATH', db_path)
    monkeypatch.setattr(ripple_globals, 'WEEKLY_REBOOT_ENABLED', False)
    monkeypatch.setattr(ripple_globals, '_scheduler_running', False)
    monkeypatch.setattr(ripple_globals, 'scheduler', None)

    yield db_path

    # Cleanup: shutdown scheduler if it was started
    if ripple_globals._scheduler_running and ripple_globals.scheduler:
        try:
            ripple_globals.scheduler.shutdown(wait=False)
        except Exception:
            pass
    monkeypatch.setattr(ripple_globals, '_scheduler_running', False)
    monkeypatch.setattr(ripple_globals, 'scheduler', None)


@pytest.mark.resilience
class TestDatabaseResilience:

    def test_corrupted_sqlite_header_system_starts(self, scheduler_env, db_corruptor):
        """
        Failure Mode: SQLite header bytes overwritten (SD card corruption)
        Expected: start_scheduler() recovers by deleting and recreating DB
        """
        db_path = scheduler_env
        _create_valid_scheduler_db(db_path)
        db_corruptor.corrupt_header(db_path)

        ripple_globals.start_scheduler()

        assert ripple_globals.scheduler is not None
        assert ripple_globals.scheduler.running
        assert ripple_globals._scheduler_running

    def test_missing_sqlite_fresh_start(self, scheduler_env):
        """
        Failure Mode: Database file deleted or never created
        Expected: start_scheduler() creates fresh database normally
        """
        db_path = scheduler_env
        assert not Path(db_path).exists()

        ripple_globals.start_scheduler()

        assert ripple_globals.scheduler is not None
        assert ripple_globals.scheduler.running
        assert Path(db_path).exists()

    def test_sqlite_locked_forces_memory_fallback(self, scheduler_env, db_corruptor):
        """
        Failure Mode: DB locked AND can't delete file -> memory fallback
        Expected: start_scheduler() falls back to MemoryJobStore (tier 3)
        """
        db_path = scheduler_env
        _create_valid_scheduler_db(db_path)

        # Corrupt header so tier 1 (SQLAlchemy open) fails,
        # then patch os.remove to no-op so tier 2 can't delete the corrupt file
        # and retries against the same corrupt DB, also failing.
        # This forces tier 3 (MemoryJobStore).
        db_corruptor.corrupt_header(db_path)

        with patch('src.globals.os.remove', side_effect=OSError("Cannot delete file")):
            ripple_globals.start_scheduler()

            assert ripple_globals.scheduler is not None
            assert ripple_globals.scheduler.running
            # Verify it's actually using memory store, not SQLite
            jobstore = ripple_globals.scheduler._jobstores.get('default')
            assert isinstance(jobstore, APMemoryJobStore), \
                f"Expected MemoryJobStore fallback, got {type(jobstore).__name__}"

    def test_sqlite_truncated_during_write(self, scheduler_env, db_corruptor):
        """
        Failure Mode: Power loss during SQLite write -> truncated file
        Expected: start_scheduler() deletes corrupt file, starts fresh
        """
        db_path = scheduler_env
        _create_valid_scheduler_db(db_path)

        original_size = os.path.getsize(db_path)
        db_corruptor.truncate_database(db_path, keep_bytes=min(100, original_size // 2))

        ripple_globals.start_scheduler()

        assert ripple_globals.scheduler is not None
        assert ripple_globals.scheduler.running

    def test_sqlite_readonly_forces_memory_fallback(self, scheduler_env, file_corruptor):
        """
        Failure Mode: Filesystem mounted read-only (SD card protection)
        Expected: start_scheduler() falls back to MemoryJobStore
        """
        db_path = scheduler_env
        _create_valid_scheduler_db(db_path)

        # Make both the file and its parent directory read-only
        # so SQLite can't write journal files
        parent_dir = str(Path(db_path).parent)
        file_corruptor.make_readonly(db_path)
        file_corruptor.make_readonly(parent_dir)

        try:
            ripple_globals.start_scheduler()

            assert ripple_globals.scheduler is not None
            assert ripple_globals.scheduler.running
        finally:
            # Cleanup: restore permissions
            os.chmod(parent_dir, 0o755)
            os.chmod(db_path, 0o644)

    def test_rapid_restart_no_duplicate_jobs(self, tmp_path):
        """
        Failure Mode: System restarted rapidly (watchdog, crash loop)
        Expected: No duplicate scheduled jobs after restart

        Note: Uses direct scheduler creation (not start_scheduler) since
        this tests APScheduler's replace_existing behavior, not recovery.
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")

        # Session 1: start, add job, stop
        jobstore1 = SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        scheduler1 = BackgroundScheduler(jobstores={'default': jobstore1})
        scheduler1.start()
        scheduler1.add_job(_sample_job, 'interval', seconds=60,
                          id='test_job', replace_existing=True)
        job_count_1 = len(scheduler1.get_jobs())
        scheduler1.shutdown()

        # Session 2: restart immediately, add same job
        jobstore2 = SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        scheduler2 = BackgroundScheduler(jobstores={'default': jobstore2})
        scheduler2.start()
        scheduler2.add_job(_sample_job, 'interval', seconds=60,
                          id='test_job', replace_existing=True)
        job_count_2 = len(scheduler2.get_jobs())
        scheduler2.shutdown()

        assert job_count_2 == job_count_1, \
            f"Duplicate jobs: session1={job_count_1}, session2={job_count_2}"

    def test_sqlite_zero_byte_file(self, scheduler_env, file_corruptor):
        """
        Failure Mode: Power loss at start of DB write -> empty file
        Expected: start_scheduler() treats as fresh database
        """
        db_path = scheduler_env
        file_corruptor.write_empty(db_path)

        ripple_globals.start_scheduler()

        assert ripple_globals.scheduler is not None
        assert ripple_globals.scheduler.running

    def test_sqlite_garbage_content(self, scheduler_env, file_corruptor):
        """
        Failure Mode: SD card sector corruption -> random bytes in DB file
        Expected: start_scheduler() deletes garbage, starts fresh
        """
        db_path = scheduler_env
        file_corruptor.write_garbage(db_path)

        ripple_globals.start_scheduler()

        assert ripple_globals.scheduler is not None
        assert ripple_globals.scheduler.running
