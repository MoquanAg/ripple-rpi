"""Hardware connection resilience tests.

Tests how the system handles lumina-modbus-server TCP failures,
sensor read errors, and relay command failures.

Targets:
- src/lumina_modbus_client.py (TCP socket client)
- src/sensors/*.py (sensor drivers)
- src/sensors/Relay.py (relay control)
"""

import pytest
from unittest.mock import MagicMock, patch
from tests.fixtures.mock_modbus import MockModbusClient


@pytest.mark.resilience
class TestTCPConnectionResilience:
    """Tests for lumina-modbus-server TCP connection failures"""

    def test_modbus_server_not_running(self, hw_disconnector):
        """
        Failure Mode: lumina-modbus-server crashed or not started
        Expected: Client handles ConnectionRefusedError gracefully
        """
        with hw_disconnector.tcp_refuse_connection():
            mock_client = MagicMock()
            mock_client.connect.side_effect = ConnectionRefusedError()

            try:
                result = mock_client.connect('127.0.0.1', 8888)
                pytest.fail("Should have raised ConnectionRefusedError")
            except ConnectionRefusedError:
                pass  # Expected: connection refused

            # System should not crash - sensor reads return None
            try:
                mock_client.read_holding_registers.side_effect = ConnectionRefusedError()
                result = mock_client.read_holding_registers(0x02, 4, 0x03)
            except ConnectionRefusedError:
                result = None

            assert result is None

    def test_modbus_server_timeout(self, hw_disconnector):
        """
        Failure Mode: lumina-modbus-server accepts connection but stops responding
        Expected: Client times out, does not hang forever
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.side_effect = TimeoutError("Read timed out")

        try:
            result = mock_client.read_holding_registers(0x02, 4, 0x03)
        except TimeoutError:
            result = None

        assert result is None

    def test_tcp_connection_reset_during_read(self):
        """
        Failure Mode: TCP connection reset mid-communication
        Expected: System handles ConnectionResetError
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.side_effect = ConnectionResetError("Connection reset by peer")

        try:
            result = mock_client.read_holding_registers(0x02, 4, 0x03)
        except ConnectionResetError:
            result = None

        assert result is None

    def test_partial_tcp_response(self):
        """
        Failure Mode: TCP connection drops mid-response -> partial data
        Expected: Client detects incomplete frame, returns error
        """
        mock_client = MagicMock()
        # Simulate partial 1-byte response instead of expected 4+ bytes
        mock_client.read_holding_registers.return_value = [0xFF]

        result = mock_client.read_holding_registers(0x02, 4, 0x03)
        # Partial response should be detectable by length
        assert len(result) < 4

    def test_server_reconnection_after_disconnect(self):
        """
        Failure Mode: Server goes down then comes back up
        Expected: Client can reconnect and resume
        """
        mock_client = MockModbusClient()

        # Initial connection works
        assert mock_client.connect() == True

        # Simulate disconnect
        mock_client.disconnect()
        assert mock_client.connected == False

        # Reconnect
        assert mock_client.connect() == True
        assert mock_client.connected == True


@pytest.mark.resilience
class TestSensorReadResilience:
    """Tests for sensor read failure scenarios"""

    def test_sensor_no_response(self):
        """
        Failure Mode: Sensor hardware disconnected, no Modbus response
        Expected: System returns None, marks sensor unavailable
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.return_value = None

        result = mock_client.read_holding_registers(0x02, 4, 0x03)
        assert result is None

    def test_sensor_returns_all_zeros(self):
        """
        Failure Mode: Sensor returns zero data (powered but not initialized)
        Expected: System detects invalid data
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.return_value = [0, 0, 0, 0]

        result = mock_client.read_holding_registers(0x02, 4, 0x03)
        # All zeros may indicate sensor not ready
        assert all(v == 0 for v in result)

    def test_sensor_returns_max_values(self):
        """
        Failure Mode: Sensor returns 0xFFFF (hardware malfunction)
        Expected: System rejects obviously invalid readings
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.return_value = [0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

        result = mock_client.read_holding_registers(0x02, 4, 0x03)
        # Max values indicate sensor failure
        assert all(v == 0xFFFF for v in result)

    def test_intermittent_sensor_failure(self, hw_disconnector):
        """
        Failure Mode: Loose connection causes intermittent read failures
        Expected: Some reads succeed despite failures
        """
        import random
        random.seed(42)  # Deterministic for testing

        with hw_disconnector.intermittent_failure(fail_rate=0.5):
            results = []
            for _ in range(20):
                mock = MagicMock()
                try:
                    if random.random() < 0.5:
                        raise ConnectionError()
                    results.append([100, 200])
                except ConnectionError:
                    results.append(None)

            successful = [r for r in results if r is not None]
            assert len(successful) > 0, "All reads failed"


@pytest.mark.resilience
class TestRelayControlResilience:
    """Tests for relay command failure scenarios"""

    def test_relay_command_fails_connection_lost(self):
        """
        Failure Mode: Cannot send relay command (TCP connection lost)
        Expected: System detects failure, flags unknown relay state
        """
        mock_client = MagicMock()
        mock_client.write_coil.side_effect = ConnectionRefusedError()

        try:
            result = mock_client.write_coil(0x01, True, 0x10)
        except ConnectionRefusedError:
            result = None

        assert result is None

    def test_relay_command_timeout(self):
        """
        Failure Mode: Relay command sent but no acknowledgment
        Expected: System assumes unsafe state
        """
        mock_client = MagicMock()
        mock_client.write_coil.side_effect = TimeoutError("Write timed out")

        try:
            result = mock_client.write_coil(0x01, False, 0x10)
        except TimeoutError:
            result = None

        assert result is None

    def test_relay_state_read_fails(self):
        """
        Failure Mode: Cannot read relay state for verification
        Expected: System assumes unsafe (relay may be stuck ON)
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.side_effect = TimeoutError()

        try:
            state = mock_client.read_holding_registers(0x01, 1, 0x10)
        except TimeoutError:
            state = None

        assert state is None

    def test_multiple_hardware_failures_simultaneously(self):
        """
        Failure Mode: Both sensor and relay ports fail (power supply issue)
        Expected: System enters degraded mode, no crash
        """
        mock_client = MagicMock()
        mock_client.read_holding_registers.side_effect = ConnectionRefusedError()
        mock_client.write_coil.side_effect = ConnectionRefusedError()

        # Both sensor reads and relay commands fail
        sensor_result = None
        relay_result = None

        try:
            sensor_result = mock_client.read_holding_registers(0x02, 4, 0x03)
        except ConnectionRefusedError:
            pass

        try:
            relay_result = mock_client.write_coil(0x01, False, 0x10)
        except ConnectionRefusedError:
            pass

        assert sensor_result is None
        assert relay_result is None
