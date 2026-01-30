"""Tests for SensorScanner probe logic and validation"""
import pytest
import struct
import math
from unittest.mock import MagicMock, call


class FakeReadResponse:
    """Mimics ModbusReadResponse from LuminaModbusClient"""

    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._error = error

    def isError(self):
        return self._error


def make_mock_client(responses=None):
    """Create a mock modbus client.

    Args:
        responses: dict mapping (slave_addr, register_addr, count) to FakeReadResponse.
                   If a tuple key is not found, returns an error response.
    """
    client = MagicMock()
    _responses = responses or {}

    def _read(port, address, count, slave_addr, baudrate=9600, timeout=1.0, device_name=None):
        key = (slave_addr, address, count)
        return _responses.get(key, FakeReadResponse(error=True))

    client.read_holding_registers = MagicMock(side_effect=_read)
    return client


def _ec_float_registers(value):
    """Pack a float into two 16-bit registers in [lo_word, hi_word] order
    matching the EC sensor byte-reordering convention."""
    packed = struct.pack('>f', value)
    hi_word, lo_word = struct.unpack('>HH', packed)
    return [lo_word, hi_word]


# ---------------------------------------------------------------------------
# pH probe tests
# ---------------------------------------------------------------------------
class TestpHProbe:
    def test_valid_ph_response(self):
        from src.sensor_scanner import SensorScanner

        # pH=7.00 (raw 700), temp=25.0 (raw 250)
        client = make_mock_client({
            (0x02, 0x0000, 2): FakeReadResponse(registers=[700, 250])
        })
        scanner = SensorScanner(client)
        result = scanner._probe_address('/dev/ttyAMA2', 9600, 0x02)
        assert result is not None
        assert result['sensor_type'] == 'ph'
        assert result['sample_reading']['ph'] == pytest.approx(7.0)
        assert result['sample_reading']['temperature'] == pytest.approx(25.0)

    def test_ph_out_of_range_high(self):
        from src.sensor_scanner import SensorScanner

        # pH raw 1401 exceeds max 1400
        client = make_mock_client({
            (0x02, 0x0000, 2): FakeReadResponse(registers=[1401, 250])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x02, 'ph')
        assert result is None

    def test_ph_zero_is_valid(self):
        from src.sensor_scanner import SensorScanner

        # pH raw 0 → pH=0.00 is valid (edge of range)
        client = make_mock_client({
            (0x02, 0x0000, 2): FakeReadResponse(registers=[0, 250])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x02, 'ph')
        assert result is not None
        assert result['sensor_type'] == 'ph'
        assert result['sample_reading']['ph'] == pytest.approx(0.0)

    def test_ph_temp_out_of_range(self):
        from src.sensor_scanner import SensorScanner

        # temp raw 1201 exceeds max 1200
        client = make_mock_client({
            (0x02, 0x0000, 2): FakeReadResponse(registers=[700, 1201])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x02, 'ph')
        assert result is None


# ---------------------------------------------------------------------------
# DO probe tests
# ---------------------------------------------------------------------------
class TestDOProbe:
    def test_valid_do_response(self):
        from src.sensor_scanner import SensorScanner

        # DO raw 850 → 8.50 mg/L
        client = make_mock_client({
            (0x04, 0x0014, 2): FakeReadResponse(registers=[850, 0])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x04, 'do')
        assert result is not None
        assert result['sensor_type'] == 'do'
        assert result['sample_reading']['do'] == pytest.approx(8.50)

    def test_do_zero_rejected(self):
        from src.sensor_scanner import SensorScanner

        # DO raw 0 is below minimum 1
        client = make_mock_client({
            (0x04, 0x0014, 2): FakeReadResponse(registers=[0, 0])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x04, 'do')
        assert result is None

    def test_do_over_20_rejected(self):
        from src.sensor_scanner import SensorScanner

        # DO raw 2001 → 20.01 mg/L exceeds max 2000
        client = make_mock_client({
            (0x04, 0x0014, 2): FakeReadResponse(registers=[2001, 0])
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x04, 'do')
        assert result is None


# ---------------------------------------------------------------------------
# EC probe tests
# ---------------------------------------------------------------------------
class TestECProbe:
    def test_valid_ec_response(self):
        from src.sensor_scanner import SensorScanner

        regs = _ec_float_registers(1.5)
        # Pad to 16 registers
        regs.extend([0] * 14)
        client = make_mock_client({
            (0x03, 0x0000, 16): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x03, 'ec')
        assert result is not None
        assert result['sensor_type'] == 'ec'
        assert result['sample_reading']['ec'] == pytest.approx(1.5, abs=0.01)

    def test_ec_nan_rejected(self):
        from src.sensor_scanner import SensorScanner

        regs = _ec_float_registers(float('nan'))
        regs.extend([0] * 14)
        client = make_mock_client({
            (0x03, 0x0000, 16): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x03, 'ec')
        assert result is None

    def test_ec_over_200_rejected(self):
        from src.sensor_scanner import SensorScanner

        regs = _ec_float_registers(201.0)
        regs.extend([0] * 14)
        client = make_mock_client({
            (0x03, 0x0000, 16): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x03, 'ec')
        assert result is None


# ---------------------------------------------------------------------------
# Water level probe tests
# ---------------------------------------------------------------------------
class TestWaterLevelProbe:
    def _make_wl_registers(self, unit=13, decimal=1, level=500, range_min=0, range_max=1000):
        """Build 8-register water level response."""
        # regs: [0]=?, [1]=?, [2]=unit, [3]=decimal, [4]=level, [5]=range_min, [6]=range_max, [7]=?
        return [0, 0, unit, decimal, level, range_min, range_max, 0]

    def test_valid_water_level_response(self):
        from src.sensor_scanner import SensorScanner

        regs = self._make_wl_registers(unit=13, decimal=1, level=500, range_min=0, range_max=1000)
        client = make_mock_client({
            (0x05, 0x0000, 8): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x05, 'water_level')
        assert result is not None
        assert result['sensor_type'] == 'water_level'
        assert result['sample_reading']['level'] == 500
        assert result['sample_reading']['range_min'] == 0
        assert result['sample_reading']['range_max'] == 1000

    def test_water_level_bad_unit(self):
        from src.sensor_scanner import SensorScanner

        # unit=8 is below valid range 9-17
        regs = self._make_wl_registers(unit=8)
        client = make_mock_client({
            (0x05, 0x0000, 8): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x05, 'water_level')
        assert result is None

    def test_water_level_bad_decimal(self):
        from src.sensor_scanner import SensorScanner

        # decimal=4 exceeds valid range 0-3
        regs = self._make_wl_registers(decimal=4)
        client = make_mock_client({
            (0x05, 0x0000, 8): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x05, 'water_level')
        assert result is None

    def test_water_level_range_inverted(self):
        from src.sensor_scanner import SensorScanner

        # range_min > range_max is invalid
        regs = self._make_wl_registers(range_min=1000, range_max=500)
        client = make_mock_client({
            (0x05, 0x0000, 8): FakeReadResponse(registers=regs)
        })
        scanner = SensorScanner(client)
        result = scanner._run_probe('/dev/ttyAMA2', 9600, 0x05, 'water_level')
        assert result is None


# ---------------------------------------------------------------------------
# Scan integration tests
# ---------------------------------------------------------------------------
class TestScanIntegration:
    def test_scan_finds_ph_sensor(self):
        from src.sensor_scanner import SensorScanner

        client = make_mock_client({
            (0x02, 0x0000, 2): FakeReadResponse(registers=[700, 250])
        })
        scanner = SensorScanner(
            client,
            ports=['/dev/ttyAMA2'],
            baud_rates=[9600],
            addr_start=0x02,
            addr_end=0x02,
        )
        results = scanner.scan()
        assert len(results) == 1
        assert results[0]['sensor_type'] == 'ph'
        assert results[0]['address'] == 0x02
        assert results[0]['port'] == '/dev/ttyAMA2'
        assert results[0]['baudrate'] == 9600

    def test_scan_short_circuit_skips_remaining_probes(self):
        from src.sensor_scanner import SensorScanner

        # Respond to EC probe (tried first in order) with valid data
        ec_regs = _ec_float_registers(1.5)
        ec_regs.extend([0] * 14)
        client = make_mock_client({
            (0x03, 0x0000, 16): FakeReadResponse(registers=ec_regs),
            # Also set up pH response — but it should NOT be tried
            (0x03, 0x0000, 2): FakeReadResponse(registers=[700, 250]),
        })
        scanner = SensorScanner(
            client,
            ports=['/dev/ttyAMA2'],
            baud_rates=[9600],
            addr_start=0x03,
            addr_end=0x03,
            short_circuit=True,
        )
        results = scanner.scan()
        assert len(results) == 1
        assert results[0]['sensor_type'] == 'ec'

        # Verify that only probes up to and including the first match were attempted.
        # EC is first in probe order, so only 1 read_holding_registers call for probe.
        calls = client.read_holding_registers.call_args_list
        assert len(calls) == 1

    def test_scan_no_short_circuit_tries_all_probes(self):
        from src.sensor_scanner import SensorScanner

        ec_regs = _ec_float_registers(1.5)
        ec_regs.extend([0] * 14)
        client = make_mock_client({
            (0x03, 0x0000, 16): FakeReadResponse(registers=ec_regs),
        })
        scanner = SensorScanner(
            client,
            ports=['/dev/ttyAMA2'],
            baud_rates=[9600],
            addr_start=0x03,
            addr_end=0x03,
            short_circuit=False,
        )
        results = scanner.scan()
        # Should still find ec
        assert any(r['sensor_type'] == 'ec' for r in results)
        # All 4 sensor types should have been probed
        assert client.read_holding_registers.call_count == 4

    def test_scan_empty_when_nothing_found(self):
        from src.sensor_scanner import SensorScanner

        # Client returns errors for everything
        client = make_mock_client({})
        scanner = SensorScanner(
            client,
            ports=['/dev/ttyAMA2'],
            baud_rates=[9600],
            addr_start=0x01,
            addr_end=0x01,
        )
        results = scanner.scan()
        assert results == []

    def test_scan_progress_callback(self):
        from src.sensor_scanner import SensorScanner

        progress_calls = []

        def on_progress(info):
            progress_calls.append(info)

        client = make_mock_client({})
        scanner = SensorScanner(
            client,
            ports=['/dev/ttyAMA2'],
            baud_rates=[9600],
            addr_start=0x01,
            addr_end=0x02,
            on_progress=on_progress,
        )
        scanner.scan()
        # Should have received a progress call for each address scanned
        assert len(progress_calls) == 2
        assert progress_calls[0]['address'] == 0x01
        assert progress_calls[1]['address'] == 0x02
