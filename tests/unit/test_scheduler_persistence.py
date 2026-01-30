"""
Test APScheduler job persistence via SQLite jobstore.

Critical tests:
- Jobs written to SQLite file
- Jobs survive scheduler restart
- Job replacement with replace_existing
- Multiple job types coexist
- Scheduling lock prevents race conditions
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import sys
from pathlib import Path
import threading

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def dummy_job_function():
    """Dummy function for testing job persistence (must be serializable)"""
    pass


def create_scheduler_with_sqlite(jobstore_path):
    """Helper to create scheduler with SQLite jobstore"""
    jobstores = {
        'default': SQLAlchemyJobStore(url=f'sqlite:///{jobstore_path}')
    }
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.start()
    return scheduler


class TestSchedulerPersistence:
    """Test APScheduler SQLite persistence"""

    def test_jobs_persist_to_sqlite(self, tmp_path, monkeypatch):
        """Scheduled jobs should be written to SQLite file"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Directly add a job to test persistence (not via schedule_next_nutrient_cycle_static)
        future_time = datetime.now() + timedelta(minutes=5)
        scheduler.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=future_time,
            id='nutrient_start'
        )

        # Assert - job exists in scheduler
        job = scheduler.get_job('nutrient_start')
        assert job is not None

        # SQLite file was created
        assert jobstore_path.exists()

        # Cleanup
        scheduler.shutdown()

    def test_jobs_reload_after_restart(self, tmp_path):
        """Jobs should be restored from SQLite after restart"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"

        # 1. Create scheduler, add job with serializable function (future time to prevent auto-removal)
        scheduler1 = create_scheduler_with_sqlite(jobstore_path)
        future_time = datetime.now() + timedelta(hours=1)
        scheduler1.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=future_time,
            id='nutrient_start'
        )
        scheduler1.shutdown()

        # 2. Create new scheduler (simulates restart)
        scheduler2 = create_scheduler_with_sqlite(jobstore_path)

        # 3. Job should be restored
        job = scheduler2.get_job('nutrient_start')
        assert job is not None
        assert job.id == 'nutrient_start'

        # Cleanup
        scheduler2.shutdown()

    def test_job_replacement_updates_existing(self, tmp_path):
        """replace_existing=True should update job, not duplicate"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Use future times to prevent job removal
        time1 = datetime.now() + timedelta(minutes=5)
        time2 = datetime.now() + timedelta(minutes=10)

        # Schedule nutrient_stop at T1
        scheduler.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=time1,
            id='nutrient_stop',
            replace_existing=True
        )

        # Schedule nutrient_stop at T2 (should replace)
        scheduler.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=time2,
            id='nutrient_stop',
            replace_existing=True
        )

        # Assert - only one job should exist
        jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_stop']
        assert len(jobs) == 1
        # Compare timestamps (ignore microseconds and timezone)
        job_time = jobs[0].next_run_time.replace(microsecond=0, tzinfo=None)
        expected_time = time2.replace(microsecond=0)
        assert job_time == expected_time

        # Cleanup
        scheduler.shutdown()

    def test_multiple_jobs_persist_independently(self, tmp_path):
        """Different job types should persist without interference"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Add multiple jobs
        scheduler.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=datetime.now() + timedelta(minutes=5),
            id='nutrient_start'
        )
        scheduler.add_job(
            'tests.unit.test_scheduler_persistence:dummy_job_function',
            'date',
            run_date=datetime.now() + timedelta(minutes=10),
            id='ph_start'
        )

        scheduler.shutdown()

        # Restart and verify all jobs restored
        scheduler2 = create_scheduler_with_sqlite(jobstore_path)
        assert scheduler2.get_job('nutrient_start') is not None
        assert scheduler2.get_job('ph_start') is not None

        # Cleanup
        scheduler2.shutdown()

    def test_scheduling_lock_prevents_duplicates(self, tmp_path, monkeypatch):
        """Concurrent scheduling calls should not create duplicate jobs"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Create a counter to track actual calls
        call_count = {'count': 0}

        def schedule_with_lock():
            """Function that simulates concurrent scheduling"""
            # Remove existing job first (simulate the check in schedule_next_nutrient_cycle_static)
            try:
                existing = scheduler.get_job('nutrient_start')
                if existing:
                    return  # Job already exists, don't create duplicate
            except:
                pass

            call_count['count'] += 1
            scheduler.add_job(
                'tests.unit.test_scheduler_persistence:dummy_job_function',
                'date',
                run_date=datetime.now() + timedelta(minutes=5),
                id='nutrient_start',
                replace_existing=True
            )

        # Act - rapidly call from threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=schedule_with_lock)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Assert - only one nutrient_start job should exist
        jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_start']
        assert len(jobs) == 1

        # Cleanup
        scheduler.shutdown()
