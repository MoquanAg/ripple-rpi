"""
GACP/GAP Audit Event Module for Ripple

Provides structured, persistent audit logging for GACP/GAP compliance.
Events are stored locally in SQLite and batch-synced to the cloud via
the Edge device's local server.

Usage:
    from audit_event import audit

    audit.emit("dosing", "nutrient_start",
               resource="NutrientPumpA",
               value={"duration": 30, "abc_ratio": [1, 1, 0]},
               source="autonomous",
               details="EC=1.2 mS/cm, target=1.5")
"""

import configparser
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Valid event types (matching Directus schema)
VALID_EVENT_TYPES = {
    "user_command", "override", "config_change", "dosing", "irrigation",
    "climate", "phase_transition", "alarm", "mode_change", "system",
}


def _read_device_id() -> str:
    """Read device ID from system.conf."""
    try:
        conf = configparser.ConfigParser()
        conf_path = os.path.join(BASE_DIR, "system.conf")
        conf.read(conf_path)
        return conf.get("SYSTEM", "deviceid", fallback="unknown-ripple")
    except Exception:
        return "unknown-ripple"


class AuditEvent(BaseModel):
    """Pydantic v2 model matching the Directus audit_events schema."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    device_id: str
    event_type: str
    action: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    resource: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    previous_value: Optional[Dict[str, Any]] = None
    source: str
    status: Optional[str] = None
    details: Optional[str] = None
    grow_cycle_id: Optional[str] = None
    synced: bool = False


class AuditStore:
    """
    Thread-safe singleton for persistent audit event storage.

    Uses SQLite with WAL mode for concurrent read/write access.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(AuditStore, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._device_id = _read_device_id()
        self._db_path = os.path.join(DATA_DIR, "audit_events.db")
        self._db_lock = threading.Lock()
        self._debounce_times: Dict[str, float] = {}
        self._init_db()
        self._initialized = True
        logger.info("AuditStore initialized at %s (device=%s)", self._db_path, self._device_id)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        action TEXT NOT NULL,
                        user_id TEXT,
                        user_name TEXT,
                        resource TEXT,
                        value TEXT,
                        previous_value TEXT,
                        source TEXT NOT NULL,
                        status TEXT,
                        details TEXT,
                        grow_cycle_id TEXT,
                        synced INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_synced
                    ON audit_events (synced, created_at)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_device_time
                    ON audit_events (device_id, timestamp)
                """)
                conn.commit()
            finally:
                conn.close()

    def _retry(self, func, max_retries=3):
        """Simple retry with backoff for SQLite busy errors."""
        import time
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return func()
            except sqlite3.OperationalError as e:
                last_exc = e
                if attempt < max_retries:
                    time.sleep(0.1 * (2 ** attempt))
        raise last_exc

    def emit(
        self,
        event_type: str,
        action: str,
        *,
        resource: Optional[str] = None,
        value: Optional[Dict[str, Any]] = None,
        previous_value: Optional[Dict[str, Any]] = None,
        source: str = "system",
        status: Optional[str] = None,
        details: Optional[str] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        grow_cycle_id: Optional[str] = None,
        device_id: Optional[str] = None,
        debounce_key: Optional[str] = None,
        debounce_seconds: float = 0,
    ) -> Optional[str]:
        """Emit an audit event — persists to SQLite and logs to text logger.

        Args:
            debounce_key: If set, suppress duplicate events with the same key
                within debounce_seconds. Useful for repetitive autonomous actions.
            debounce_seconds: Minimum interval between events with the same
                debounce_key (default 0 = no debouncing).
        """
        if debounce_key and debounce_seconds > 0:
            now = time.monotonic()
            last = self._debounce_times.get(debounce_key, 0)
            if now - last < debounce_seconds:
                return None
            self._debounce_times[debounce_key] = now

        if event_type not in VALID_EVENT_TYPES:
            logger.warning("Unknown audit event_type: %s", event_type)

        event = AuditEvent(
            device_id=device_id or self._device_id,
            event_type=event_type,
            action=action,
            resource=resource,
            value=value,
            previous_value=previous_value,
            source=source,
            status=status,
            details=details,
            user_id=user_id,
            user_name=user_name,
            grow_cycle_id=grow_cycle_id,
        )

        # Log to text logger for backward compatibility
        log_parts = [f"AUDIT {event_type}/{action}"]
        if resource:
            log_parts.append(f"resource={resource}")
        if value:
            log_parts.append(f"value={value}")
        if user_name:
            log_parts.append(f"by={user_name}")
        if status:
            log_parts.append(f"status={status}")
        logger.info(" ".join(log_parts))

        try:
            def _insert():
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        conn.execute(
                            """INSERT INTO audit_events
                            (id, timestamp, device_id, event_type, action,
                             user_id, user_name, resource, value, previous_value,
                             source, status, details, grow_cycle_id, synced)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                            (
                                event.id,
                                event.timestamp,
                                event.device_id,
                                event.event_type,
                                event.action,
                                event.user_id,
                                event.user_name,
                                event.resource,
                                json.dumps(event.value) if event.value else None,
                                json.dumps(event.previous_value) if event.previous_value else None,
                                event.source,
                                event.status,
                                event.details,
                                event.grow_cycle_id,
                            ),
                        )
                        conn.commit()
                    finally:
                        conn.close()

            self._retry(_insert)
            return event.id

        except Exception as e:
            logger.error("Failed to persist audit event: %s", e)
            return None

    def get_unsynced(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get unsynced events for batch upload."""
        try:
            def _query():
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        cursor = conn.execute(
                            """SELECT id, timestamp, device_id, event_type, action,
                                      user_id, user_name, resource, value, previous_value,
                                      source, status, details, grow_cycle_id
                               FROM audit_events
                               WHERE synced = 0
                               ORDER BY created_at ASC
                               LIMIT ?""",
                            (limit,),
                        )
                        rows = cursor.fetchall()
                        events = []
                        for row in rows:
                            event = dict(row)
                            if event["value"]:
                                event["value"] = json.loads(event["value"])
                            if event["previous_value"]:
                                event["previous_value"] = json.loads(event["previous_value"])
                            events.append(event)
                        return events
                    finally:
                        conn.close()

            return self._retry(_query)

        except Exception as e:
            logger.error("Failed to query unsynced audit events: %s", e)
            return []

    def mark_synced(self, event_ids: List[str]) -> int:
        """Mark events as synced after successful upload."""
        if not event_ids:
            return 0

        try:
            def _update():
                with self._db_lock:
                    conn = self._get_connection()
                    try:
                        placeholders = ",".join("?" for _ in event_ids)
                        cursor = conn.execute(
                            f"UPDATE audit_events SET synced = 1 WHERE id IN ({placeholders})",
                            event_ids,
                        )
                        conn.commit()
                        return cursor.rowcount
                    finally:
                        conn.close()

            return self._retry(_update)

        except Exception as e:
            logger.error("Failed to mark audit events as synced: %s", e)
            return 0


# Global singleton instance
audit = AuditStore()
