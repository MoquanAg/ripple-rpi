"""Fixtures for resilience testing"""

import pytest
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tests.fixtures.error_injection import FileCorruptor, DatabaseCorruptor, HardwareDisconnector


@pytest.fixture
def file_corruptor():
    """File system corruption utility"""
    return FileCorruptor()


@pytest.fixture
def db_corruptor():
    """Database corruption utility"""
    return DatabaseCorruptor()


@pytest.fixture
def hw_disconnector():
    """Hardware disconnection utility"""
    return HardwareDisconnector()
