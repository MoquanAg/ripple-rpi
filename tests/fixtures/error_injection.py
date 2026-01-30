"""Error injection utilities for resilience testing.

Provides FileCorruptor, DatabaseCorruptor, and HardwareDisconnector
classes for simulating infrastructure failures.
"""

import os
import stat
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


class FileCorruptor:
    """Inject file system failures for testing"""

    def write_truncated(self, path, content, truncate_at):
        """Simulate power loss during write (partial content)"""
        Path(path).write_text(content[:truncate_at])

    def write_garbage(self, path):
        """Simulate SD card corruption (random bytes)"""
        Path(path).write_bytes(b'\x00\x89\xff\xfe\xab\xcd\x00\x01\x02\x03' * 10)

    def make_readonly(self, path):
        """Simulate read-only filesystem"""
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    def make_unreadable(self, path):
        """Simulate file gone or inaccessible"""
        os.chmod(path, 0o000)

    def write_empty(self, path):
        """Simulate zero-length file (power loss at start of write)"""
        Path(path).write_text("")


class DatabaseCorruptor:
    """Inject SQLite database failures for testing"""

    def corrupt_header(self, db_path):
        """Overwrite SQLite header bytes (first 16 bytes)"""
        with open(db_path, 'r+b') as f:
            f.write(b'\x00' * 16)

    @contextmanager
    def lock_database(self, db_path):
        """Hold exclusive lock on database file"""
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN EXCLUSIVE")
        try:
            yield conn
        finally:
            conn.close()

    def truncate_database(self, db_path, keep_bytes):
        """Simulate power loss during database write"""
        with open(db_path, 'r+b') as f:
            f.truncate(keep_bytes)


class HardwareDisconnector:
    """Inject hardware connection failures for testing"""

    @contextmanager
    def tcp_refuse_connection(self, target='src.lumina_modbus_client.LuminaModbusClient'):
        """Simulate lumina-modbus-server not running"""
        mock = MagicMock()
        mock.connect.side_effect = ConnectionRefusedError("Connection refused")
        mock.read_holding_registers.side_effect = ConnectionRefusedError("Connection refused")
        mock.write_coil.side_effect = ConnectionRefusedError("Connection refused")
        with patch(target, return_value=mock):
            yield mock

    @contextmanager
    def tcp_timeout(self, target='src.lumina_modbus_client.LuminaModbusClient'):
        """Simulate lumina-modbus-server hanging"""
        mock = MagicMock()
        mock.connect.side_effect = TimeoutError("Connection timed out")
        mock.read_holding_registers.side_effect = TimeoutError("Read timed out")
        mock.write_coil.side_effect = TimeoutError("Write timed out")
        with patch(target, return_value=mock):
            yield mock

    @contextmanager
    def tcp_connection_reset(self, target='src.lumina_modbus_client.LuminaModbusClient'):
        """Simulate connection reset mid-communication"""
        mock = MagicMock()
        mock.connect.return_value = True
        mock.read_holding_registers.side_effect = ConnectionResetError("Connection reset by peer")
        mock.write_coil.side_effect = ConnectionResetError("Connection reset by peer")
        with patch(target, return_value=mock):
            yield mock

    @contextmanager
    def intermittent_failure(self, fail_rate=0.5, target='src.lumina_modbus_client.LuminaModbusClient'):
        """Simulate intermittent connection (fails N% of the time)"""
        import random
        mock = MagicMock()
        call_count = [0]

        def maybe_fail(*args, **kwargs):
            call_count[0] += 1
            if random.random() < fail_rate:
                raise ConnectionError("Intermittent failure")
            return [0] * 4  # Default sensor response

        mock.connect.return_value = True
        mock.read_holding_registers.side_effect = maybe_fail
        with patch(target, return_value=mock):
            yield mock
