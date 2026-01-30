"""Dosing pump runtime tracking for overdose prevention"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class DosingRuntimeTracker:
    """
    Track dosing pump runtime to prevent overdose.

    Enforces 60 minute daily limit for all dosing pumps combined.
    Runtime resets at midnight.
    """

    DAILY_LIMIT_SECONDS = 3600  # 60 minutes

    def __init__(self, storage_path: str):
        """
        Initialize runtime tracker.

        Args:
            storage_path: Path to JSON file for persistent storage
        """
        self.storage_path = Path(storage_path)
        self.history: Dict[str, int] = {}  # date -> total_seconds
        self.load_history()

    def load_history(self):
        """Load runtime history from disk"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    self.history = json.load(f)
            except (json.JSONDecodeError, IOError, UnicodeDecodeError):
                self.history = {}
        else:
            self.history = {}

    def save_history(self):
        """Save runtime history to disk"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.history, f, indent=2)

    def get_today_key(self) -> str:
        """Get today's date key (YYYY-MM-DD)"""
        return datetime.now().strftime("%Y-%m-%d")

    def get_today_total_runtime(self) -> int:
        """
        Get total dosing runtime for today.

        Returns:
            Total seconds of dosing pump runtime today
        """
        today_key = self.get_today_key()
        return self.history.get(today_key, 0)

    def add_dosing_event(self, pump_name: str, duration_seconds: int):
        """
        Record a dosing event.

        Args:
            pump_name: Name of dosing pump (NutrientPumpA, pHPlusPump, etc.)
            duration_seconds: How long the pump ran
        """
        today_key = self.get_today_key()
        current_runtime = self.history.get(today_key, 0)
        self.history[today_key] = current_runtime + duration_seconds
        self.save_history()

    def can_dose(self, planned_duration: int) -> bool:
        """
        Check if dosing is allowed within daily limit.

        Args:
            planned_duration: Seconds the pump will run

        Returns:
            True if within limit, False if would exceed
        """
        current_runtime = self.get_today_total_runtime()
        return (current_runtime + planned_duration) <= self.DAILY_LIMIT_SECONDS
