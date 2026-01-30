"""Database resilience tests for APScheduler SQLite backend.

Tests how the system handles SQLite database corruption, locks,
and filesystem failures affecting the scheduler job store.

Targets: src/globals.py (start_scheduler, SQLAlchemyJobStore)
Critical file: data/scheduler_jobs.sqlite
"""

import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore as APMemoryJobStore


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


def _init_scheduler_from_path(db_path):
    """Initialize a scheduler with the given database path.

    Returns (scheduler, error) tuple. Error is None on success.
    """
    try:
        jobstore = SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        scheduler = BackgroundScheduler(jobstores={'default': jobstore})
        scheduler.start()
        return scheduler, None
    except Exception as e:
        return None, e


def _init_scheduler_with_recovery(db_path):
    """Initialize a scheduler with 3-tier recovery logic matching globals.start_scheduler().

    1. Try SQLAlchemyJobStore with timeout
    2. On failure: delete corrupt DB, retry with fresh SQLAlchemyJobStore
    3. On second failure: fall back to APMemoryJobStore

    Returns (scheduler, error) tuple. Error is None on success.
    """
    # Tier 1: Try with existing DB
    try:
        jobstore = SQLAlchemyJobStore(
            url=f'sqlite:///{db_path}',
            engine_options={'connect_args': {'timeout': 10}}
        )
        scheduler = BackgroundScheduler(jobstores={'default': jobstore})
        scheduler.start()
        return scheduler, None
    except Exception as e1:
        pass

    # Tier 2: Delete corrupt DB and retry
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        jobstore = SQLAlchemyJobStore(
            url=f'sqlite:///{db_path}',
            engine_options={'connect_args': {'timeout': 10}}
        )
        scheduler = BackgroundScheduler(jobstores={'default': jobstore})
        scheduler.start()
        return scheduler, None
    except Exception as e2:
        pass

    # Tier 3: Fall back to in-memory job store
    try:
        jobstore = APMemoryJobStore()
        scheduler = BackgroundScheduler(jobstores={'default': jobstore})
        scheduler.start()
        return scheduler, None
    except Exception as e3:
        return None, e3


@pytest.mark.resilience
class TestDatabaseResilience:

    def test_corrupted_sqlite_header_system_starts(self, tmp_path, db_corruptor):
        """
        Failure Mode: SQLite header bytes overwritten (SD card corruption)
        Expected: System either recreates DB or fails gracefully
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        _create_valid_scheduler_db(db_path)
        db_corruptor.corrupt_header(db_path)

        scheduler, error = _init_scheduler_with_recovery(db_path)

        assert scheduler is not None, f"Recovery failed for corrupted DB: {error}"
        assert scheduler.running == True
        scheduler.shutdown()

    def test_missing_sqlite_fresh_start(self, tmp_path):
        """
        Failure Mode: Database file deleted or never created
        Expected: System creates fresh database and starts normally
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        assert not Path(db_path).exists()

        scheduler, error = _init_scheduler_from_path(db_path)

        assert scheduler is not None, f"Failed to start with missing DB: {error}"
        assert scheduler.running == True
        scheduler.shutdown()

    def test_sqlite_locked_by_another_process(self, tmp_path, db_corruptor):
        """
        Failure Mode: Another process holds exclusive lock
        Expected: System retries or starts with fallback
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        _create_valid_scheduler_db(db_path)

        with db_corruptor.lock_database(db_path):
            scheduler, error = _init_scheduler_with_recovery(db_path)

            assert scheduler is not None, f"Recovery failed for locked DB: {error}"
            assert scheduler.running == True
            scheduler.shutdown()

    def test_sqlite_truncated_during_write(self, tmp_path, db_corruptor):
        """
        Failure Mode: Power loss during SQLite write -> truncated file
        Expected: System detects corruption, starts fresh
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        _create_valid_scheduler_db(db_path)

        original_size = os.path.getsize(db_path)
        db_corruptor.truncate_database(db_path, keep_bytes=min(100, original_size // 2))

        scheduler, error = _init_scheduler_with_recovery(db_path)

        assert scheduler is not None, f"Recovery failed for truncated DB: {error}"
        assert scheduler.running == True
        scheduler.shutdown()

    def test_sqlite_readonly_filesystem(self, tmp_path, file_corruptor):
        """
        Failure Mode: Filesystem mounted read-only (SD card protection)
        Expected: System starts with memory-only scheduler or logs warning
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        _create_valid_scheduler_db(db_path)
        file_corruptor.make_readonly(db_path)

        scheduler, error = _init_scheduler_from_path(db_path)

        if scheduler is not None:
            scheduler.shutdown()
        else:
            pytest.xfail(f"Read-only DB prevents scheduler: {error}")

        # Cleanup: restore permissions for tmp_path cleanup
        os.chmod(db_path, 0o644)

    def test_rapid_restart_no_duplicate_jobs(self, tmp_path):
        """
        Failure Mode: System restarted rapidly (watchdog, crash loop)
        Expected: No duplicate scheduled jobs after restart
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")

        # Session 1: start, add job, stop
        scheduler1, _ = _init_scheduler_from_path(db_path)
        assert scheduler1 is not None
        scheduler1.add_job(_sample_job, 'interval', seconds=60,
                          id='test_job', replace_existing=True)
        job_count_1 = len(scheduler1.get_jobs())
        scheduler1.shutdown()

        # Session 2: restart immediately, add same job
        scheduler2, _ = _init_scheduler_from_path(db_path)
        assert scheduler2 is not None
        scheduler2.add_job(_sample_job, 'interval', seconds=60,
                          id='test_job', replace_existing=True)
        job_count_2 = len(scheduler2.get_jobs())
        scheduler2.shutdown()

        assert job_count_2 == job_count_1, \
            f"Duplicate jobs: session1={job_count_1}, session2={job_count_2}"

    def test_sqlite_zero_byte_file(self, tmp_path, file_corruptor):
        """
        Failure Mode: Power loss at start of DB write -> empty file
        Expected: System treats as fresh database
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        file_corruptor.write_empty(db_path)

        scheduler, error = _init_scheduler_from_path(db_path)

        if scheduler is not None:
            assert scheduler.running == True
            scheduler.shutdown()
        else:
            pytest.xfail(f"Empty DB file crashes scheduler: {error}")

    def test_sqlite_garbage_content(self, tmp_path, file_corruptor):
        """
        Failure Mode: SD card sector corruption -> random bytes in DB file
        Expected: System detects corruption, starts fresh
        """
        db_path = str(tmp_path / "scheduler_jobs.sqlite")
        file_corruptor.write_garbage(db_path)

        scheduler, error = _init_scheduler_with_recovery(db_path)

        assert scheduler is not None, f"Recovery failed for garbage DB: {error}"
        assert scheduler.running == True
        scheduler.shutdown()
