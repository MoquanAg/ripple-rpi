# Ripple ESP32 Firmware Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build MicroPython firmware for ESP32-S3 that reads sensors and controls relays via direct Modbus RTU, communicates with lumina-edge via WebSocket, and operates in hybrid passive/autonomous mode.

**Architecture:** ESP32-S3 connects to sensors (UART0, 9600 baud) and relay board (UART1, 38400 baud) using raw Modbus RTU. It connects to lumina-edge's local device server (WebSocket on port 9090) to report telemetry and receive commands. Normally passive (edge sends relay commands), it caches the last schedule to flash and falls back to autonomous execution if the connection drops.

**Tech Stack:** MicroPython 1.24+, ESP32-S3 (dual-core, 512KB SRAM, WiFi), uasyncio, LittleFS

---

## Repository Setup

**Repo:** `~/dev/ripple-esp`

```
ripple-esp/
├── main.py              # uasyncio entry point, state machine
├── boot.py              # WiFi connect, early init
├── config.py            # NVS/flash config read/write
├── modbus_rtu.py        # CRC-16, frame build/parse, UART send/receive
├── sensors.py           # pH, EC, DO, WaterLevel — Modbus reads, JSON formatting
├── relay.py             # Relay board — read status, write coils
├── ws_client.py         # WebSocket client to lumina-edge:9090
├── scheduler.py         # Cached schedule executor for autonomous mode
├── config.json          # Default config (WiFi, edge URL, sensor addresses, intervals)
├── tests/               # Host-side tests (run on desktop Python, mock UART)
│   ├── test_modbus_rtu.py
│   ├── test_sensors.py
│   ├── test_relay.py
│   ├── test_scheduler.py
│   └── conftest.py
└── README.md
```

---

## Data Contract

The ESP32 produces sensor JSON in the **exact same format** as ripple-rpi's `saved_sensor_data.json`. This is what gets sent via WebSocket as `device_data`. lumina-edge already knows how to parse it.

```json
{
  "data": {
    "water_metrics": {
      "water_level": {
        "measurements": {
          "name": "water_metrics",
          "points": [{
            "tags": {"sensor": "water_level", "measurement": "level", "location": "<name>"},
            "fields": {"value": 85.0, "temperature": null, "pressure_unit": null, "decimal_places": null, "range_min": 0, "range_max": 200, "zero_offset": null},
            "timestamp": "2026-01-31T12:00:00+0800"
          }]
        }
      },
      "ph": {
        "measurements": {
          "name": "water_metrics",
          "points": [{
            "tags": {"sensor": "ph", "measurement": "ph", "location": "<name>"},
            "fields": {"value": 6.10, "temperature": 25.0, "offset": null},
            "timestamp": "2026-01-31T12:00:00+0800"
          }]
        }
      },
      "ec": {
        "measurements": {
          "name": "water_metrics",
          "points": [{
            "tags": {"sensor": "ec", "measurement": "ec", "location": "<name>"},
            "fields": {"value": 1.80, "tds": 0.90, "salinity": 0.99, "temperature": 25.0, "resistance": 1000.0, "ec_constant": 1.0, "compensation_coef": 0.02, "manual_temp": 25.0, "temp_offset": null, "electrode_sensitivity": null, "compensation_mode": null, "sensor_type": null},
            "timestamp": "2026-01-31T12:00:00+0800"
          }]
        }
      }
    },
    "relay_metrics": {
      "measurements": {
        "name": "relay_metrics",
        "points": [{
          "tags": {"relay_board": "relayone", "port_index": 0, "port_type": "assigned", "device": "NutrientPumpA"},
          "fields": {"status": false, "is_assigned": true, "raw_status": false},
          "timestamp": "2026-01-31T12:00:00+0800"
        }]
      },
      "configuration": {
        "relay_configuration": {
          "relayone": {
            "total_ports": 16,
            "assigned_ports": [0,1,2,3,4,5,6,7,8,9,10,11],
            "unassigned_ports": [12,13,14,15]
          }
        }
      }
    }
  },
  "relays": {
    "last_updated": "2026-01-31T12:00:00+0800",
    "relayone": {
      "RELAYONE": {
        "RELAYONE": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
      }
    }
  },
  "devices": {
    "last_updated": "2026-01-31T12:00:00+0800"
  }
}
```

### Relay Port Mapping (hardcoded, matches ripple-rpi)

```
0:  NutrientPumpA       6:  ValveTankToOutside      12: (unassigned)
1:  NutrientPumpB       7:  MixingPump              13: (unassigned)
2:  NutrientPumpC       8:  PumpFromTankToGutters    14: (unassigned)
3:  pHUpPump            9:  SprinklerA              15: (unassigned)
4:  pHDownPump          10: SprinklerB
5:  ValveOutsideToTank  11: PumpFromCollectorTrayToTank
```

---

## WebSocket Protocol (ESP32 ↔ lumina-edge)

### Connection

```
ws://edge-host:9090/ws/device?device_id=<DEVICE_ID>&device_secret=<DEVICE_SECRET>
```

### ESP32 → Edge

**Sensor telemetry** (every 30s, or 3s in realtime mode):
```json
{"type": "device_data", "device_id": "ripple-esp-001", "version": "1.0.0", "time": "2026-01-31T12:00:00+0800", "data": { <saved_sensor_data format above> }}
```

**Heartbeat** (every 20s):
```json
{"type": "heartbeat", "device_id": "ripple-esp-001", "timestamp": "2026-01-31T12:00:00+0800", "version": "1.0.0"}
```

**Command response**:
```json
{"type": "device_command_response", "command_id": "<uuid>", "success": true, "message": "Relay 3 turned on"}
```

### Edge → ESP32

**Relay command**:
```json
{"type": "device_command", "command_id": "<uuid>", "command": "NutrientPumpA", "params": {"state": true, "duration_s": 120}, "timestamp": "..."}
```

**Time sync** (on connect + periodic):
```json
{"type": "time_sync", "utc": 1706659200}
```

**Schedule update** (on connect + on change):
```json
{"type": "schedule_update", "schedule": [{"name": "nutrient_a", "port": 0, "on_s": 60, "interval_s": 7200, "enabled": true}]}
```

---

## Modbus RTU Reference

### CRC-16 (0xA001 polynomial)
```python
def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # low byte first
```

### Sensor Commands (UART0, 9600 baud)

| Sensor | Address | Command (hex, before CRC) | Response | Parsing |
|--------|---------|---------------------------|----------|---------|
| pH | 0x11 | `11 03 00 00 00 02` | 9 bytes | pH = bytes[3:5] big-endian / 100.0, temp = bytes[5:7] / 10.0 |
| EC | 0x21 | `21 03 00 00 00 10` | 37 bytes | 32-bit floats, byte-swapped (see below) |
| DO | 0x40 | `40 03 00 14 00 02` | 9 bytes | DO = bytes[3:5] big-endian / 100.0 |
| Water Level | 0x31 | `31 03 00 00 00 08` | 21 bytes | level = signed int16 at bytes[11:13] |

**EC float parsing** (byte swap within each 4-byte group):
```python
# For register at data offset i (0-based from byte 3 of response):
raw = data[3 + i*4 : 3 + i*4 + 4]
swapped = bytes([raw[2], raw[3], raw[0], raw[1]])
value = struct.unpack('>f', swapped)[0]
```

### Relay Commands (UART1, 38400 baud, address 0x01)

| Operation | Command (hex, before CRC) | Response |
|-----------|---------------------------|----------|
| Read all 16 coils | `01 01 00 00 00 10` | 7 bytes — status bits in bytes[3:5] |
| Turn ON port N | `01 05 00 NN FF 00` | 8 bytes echo |
| Turn OFF port N | `01 05 00 NN 00 00` | 8 bytes echo |

**Status parsing**: byte[3] bits 0-7 = ports 0-7, byte[4] bits 0-7 = ports 8-15.

---

## State Machine

```
BOOT → CONNECTING → SYNCING → PASSIVE ←→ AUTONOMOUS
                                  ↑            │
                                  └── reconnect ┘
```

| State | Entry Condition | Behavior |
|-------|----------------|----------|
| BOOT | Power on | Init UARTs, load config.json from flash, load cached schedule |
| CONNECTING | After boot, or after disconnect | Connect WiFi → connect WS, exponential backoff (1s→30s max) |
| SYNCING | WS connected | Request time_sync + schedule from edge, set RTC, cache schedule to flash |
| PASSIVE | Sync complete | Poll sensors on interval, report via WS, execute relay commands from edge |
| AUTONOMOUS | WS disconnected >30s | Execute cached schedule using RTC, buffer sensor readings in RAM (max 100) |

**Transition back**: AUTONOMOUS → CONNECTING → SYNCING → PASSIVE (flush buffered readings on reconnect).

---

## Tasks

### Task 1: Initialize repo and project skeleton

**Files:**
- Create: `~/dev/ripple-esp/` (git init)
- Create: `config.json`, `boot.py`, `main.py` (stubs)
- Create: `tests/conftest.py`

**Step 1: Create repo and skeleton files**

```bash
mkdir -p ~/dev/ripple-esp/tests
cd ~/dev/ripple-esp
git init
```

**Step 2: Write config.json with defaults**

```json
{
  "wifi_ssid": "",
  "wifi_password": "",
  "edge_host": "192.168.1.100",
  "edge_port": 9090,
  "device_id": "ripple-esp-001",
  "device_secret": "",
  "sensor_poll_s": 30,
  "heartbeat_s": 20,
  "autonomous_timeout_s": 30,
  "sensor_uart_tx": 17,
  "sensor_uart_rx": 18,
  "relay_uart_tx": 15,
  "relay_uart_rx": 16,
  "sensors": {
    "ph": {"address": 17, "name": "ph_sensor"},
    "ec": {"address": 33, "name": "ec_sensor"},
    "do": {"address": 64, "name": "do_sensor"},
    "water_level": {"address": 49, "name": "water_level_sensor"}
  },
  "relay_address": 1,
  "relay_port_map": {
    "0": "NutrientPumpA",
    "1": "NutrientPumpB",
    "2": "NutrientPumpC",
    "3": "pHUpPump",
    "4": "pHDownPump",
    "5": "ValveOutsideToTank",
    "6": "ValveTankToOutside",
    "7": "MixingPump",
    "8": "PumpFromTankToGutters",
    "9": "SprinklerA",
    "10": "SprinklerB",
    "11": "PumpFromCollectorTrayToTank"
  },
  "utc_offset_hours": 8
}
```

**Step 3: Write boot.py stub**

```python
# boot.py — runs on power-up before main.py
import json

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def connect_wifi(ssid, password):
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            wlan.connect(ssid, password)
            import time
            timeout = 10
            while not wlan.isconnected() and timeout > 0:
                time.sleep(1)
                timeout -= 1
        return wlan.isconnected()
    except ImportError:
        # Running on desktop Python for testing
        return False

config = load_config()
connect_wifi(config["wifi_ssid"], config["wifi_password"])
```

**Step 4: Write main.py stub**

```python
# main.py — uasyncio entry point
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

async def main():
    print("ripple-esp starting")

asyncio.run(main())
```

**Step 5: Write tests/conftest.py**

```python
import sys
import os

# Add project root to path so tests can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: initialize ripple-esp project skeleton"
```

---

### Task 2: Modbus RTU — CRC-16 and frame builder

**Files:**
- Create: `modbus_rtu.py`
- Create: `tests/test_modbus_rtu.py`

**Step 1: Write failing tests for CRC-16 and frame building**

```python
# tests/test_modbus_rtu.py
import struct
from modbus_rtu import crc16, build_read_registers, build_write_coil, build_read_coils, parse_response, ModbusError

class TestCRC16:
    def test_known_vector(self):
        # pH read command: 11 03 00 00 00 02
        data = bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02])
        crc = crc16(data)
        assert len(crc) == 2
        # Verify round-trip: full frame CRC should be 0
        frame = data + crc
        check = crc16(frame)
        # CRC of valid frame = 0x0000
        assert crc16(frame[:-2]) == frame[-2:]

    def test_empty_data(self):
        crc = crc16(b"")
        assert crc == bytes([0xFF, 0xFF])

    def test_single_byte(self):
        crc = crc16(bytes([0x01]))
        assert len(crc) == 2

class TestBuildReadRegisters:
    def test_ph_command(self):
        frame = build_read_registers(slave=0x11, start_reg=0x0000, count=2)
        assert frame[0] == 0x11
        assert frame[1] == 0x03
        assert frame[2:4] == bytes([0x00, 0x00])
        assert frame[4:6] == bytes([0x00, 0x02])
        assert len(frame) == 8  # 6 data + 2 CRC

    def test_ec_command(self):
        frame = build_read_registers(slave=0x21, start_reg=0x0000, count=16)
        assert frame[0] == 0x21
        assert frame[4:6] == bytes([0x00, 0x10])
        assert len(frame) == 8

    def test_water_level_command(self):
        frame = build_read_registers(slave=0x31, start_reg=0x0000, count=8)
        assert frame[0] == 0x31

    def test_do_command(self):
        frame = build_read_registers(slave=0x40, start_reg=0x0014, count=2)
        assert frame[0] == 0x40
        assert frame[2:4] == bytes([0x00, 0x14])

class TestBuildReadCoils:
    def test_read_16_coils(self):
        frame = build_read_coils(slave=0x01, start_addr=0x0000, count=16)
        assert frame[0] == 0x01
        assert frame[1] == 0x01
        assert len(frame) == 8

class TestBuildWriteCoil:
    def test_turn_on(self):
        frame = build_write_coil(slave=0x01, coil_addr=3, value=True)
        assert frame[0] == 0x01
        assert frame[1] == 0x05
        assert frame[2:4] == bytes([0x00, 0x03])
        assert frame[4:6] == bytes([0xFF, 0x00])
        assert len(frame) == 8

    def test_turn_off(self):
        frame = build_write_coil(slave=0x01, coil_addr=3, value=False)
        assert frame[4:6] == bytes([0x00, 0x00])

class TestParseResponse:
    def test_invalid_crc_raises(self):
        # Valid response with corrupted last byte
        data = bytes([0x11, 0x03, 0x04, 0x02, 0x6A, 0x00, 0xFA, 0x00, 0x00])
        try:
            parse_response(data)
            assert False, "Should have raised ModbusError"
        except ModbusError:
            pass

    def test_valid_response(self):
        # Build a response with correct CRC
        payload = bytes([0x11, 0x03, 0x04, 0x02, 0x6A, 0x00, 0xFA])
        crc = crc16(payload)
        data = payload + crc
        result = parse_response(data)
        assert result["slave"] == 0x11
        assert result["function"] == 0x03
        assert result["data"] == bytes([0x02, 0x6A, 0x00, 0xFA])

    def test_error_response(self):
        # Function code with error bit set (0x83 = 0x03 | 0x80)
        payload = bytes([0x11, 0x83, 0x02])
        crc = crc16(payload)
        data = payload + crc
        try:
            parse_response(data)
            assert False, "Should have raised ModbusError"
        except ModbusError as e:
            assert "exception" in str(e).lower() or "error" in str(e).lower()
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_modbus_rtu.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Implement modbus_rtu.py**

```python
# modbus_rtu.py — Modbus RTU frame builder/parser with CRC-16
import struct


class ModbusError(Exception):
    pass


def crc16(data):
    """CRC-16/Modbus (polynomial 0xA001)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_read_registers(slave, start_reg, count):
    """Build Modbus function 0x03 (Read Holding Registers) frame."""
    payload = struct.pack(">BBHH", slave, 0x03, start_reg, count)
    return payload + crc16(payload)


def build_read_coils(slave, start_addr, count):
    """Build Modbus function 0x01 (Read Coil Status) frame."""
    payload = struct.pack(">BBHH", slave, 0x01, start_addr, count)
    return payload + crc16(payload)


def build_write_coil(slave, coil_addr, value):
    """Build Modbus function 0x05 (Write Single Coil) frame."""
    coil_value = 0xFF00 if value else 0x0000
    payload = struct.pack(">BBHH", slave, 0x05, coil_addr, coil_value)
    return payload + crc16(payload)


def parse_response(data):
    """Parse and validate a Modbus RTU response.

    Returns dict with keys: slave, function, data.
    Raises ModbusError on CRC mismatch or Modbus exception response.
    """
    if len(data) < 5:
        raise ModbusError(f"Response too short: {len(data)} bytes")

    # Verify CRC
    received_crc = data[-2:]
    calculated_crc = crc16(data[:-2])
    if received_crc != calculated_crc:
        raise ModbusError(f"CRC mismatch: received {received_crc.hex()}, calculated {calculated_crc.hex()}")

    slave = data[0]
    function = data[1]

    # Check error bit (bit 7 set = exception response)
    if function & 0x80:
        exception_code = data[2] if len(data) > 2 else 0
        raise ModbusError(f"Modbus exception: function 0x{function:02X}, code {exception_code}")

    # Extract payload (between header and CRC)
    if function in (0x03, 0x01):
        byte_count = data[2]
        payload = data[3:3 + byte_count]
    elif function == 0x05:
        payload = data[2:-2]
    else:
        payload = data[2:-2]

    return {"slave": slave, "function": function, "data": payload}
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_modbus_rtu.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add modbus_rtu.py tests/test_modbus_rtu.py
git commit -m "feat: add Modbus RTU CRC-16 and frame builder/parser"
```

---

### Task 3: Sensor drivers — pH, EC, DO, WaterLevel

**Files:**
- Create: `sensors.py`
- Create: `tests/test_sensors.py`

**Step 1: Write failing tests**

```python
# tests/test_sensors.py
import struct
from unittest.mock import MagicMock
from modbus_rtu import crc16
from sensors import SensorReader

def _make_mock_uart(response_bytes):
    """Create a mock UART that returns predefined bytes."""
    uart = MagicMock()
    uart.read = MagicMock(return_value=response_bytes)
    uart.write = MagicMock()
    uart.any = MagicMock(return_value=len(response_bytes))
    return uart

def _build_response(slave, func, payload_bytes):
    """Build a valid Modbus response with CRC."""
    frame = bytes([slave, func, len(payload_bytes)]) + payload_bytes
    return frame + crc16(frame)

class TestReadPH:
    def test_parses_ph_and_temperature(self):
        # pH = 6.10 → raw 610, temp = 25.0 → raw 250
        payload = struct.pack(">HH", 610, 250)
        response = _build_response(0x11, 0x03, payload)
        uart = _make_mock_uart(response)
        reader = SensorReader(uart)
        result = reader.read_ph(address=0x11, name="ph_sensor")
        assert abs(result["value"] - 6.10) < 0.01
        assert abs(result["temperature"] - 25.0) < 0.1

    def test_returns_none_on_no_response(self):
        uart = _make_mock_uart(None)
        reader = SensorReader(uart)
        result = reader.read_ph(address=0x11, name="ph_sensor")
        assert result is None

class TestReadEC:
    def test_parses_ec_value(self):
        # EC = 1.80 mS/cm as IEEE 754 float, byte-swapped
        ec_val = 1.80
        ec_bytes = struct.pack(">f", ec_val)
        # Sensor sends bytes swapped: [b2, b3, b0, b1]
        swapped = bytes([ec_bytes[2], ec_bytes[3], ec_bytes[0], ec_bytes[1]])
        # Build 16 registers (8 floats) — pad remaining with zeros
        payload = swapped + b"\x00" * (32 - 4)
        response = _build_response(0x21, 0x03, payload)
        uart = _make_mock_uart(response)
        reader = SensorReader(uart)
        result = reader.read_ec(address=0x21, name="ec_sensor")
        assert abs(result["value"] - 1.80) < 0.01

class TestReadDO:
    def test_parses_do_value(self):
        # DO = 7.20 mg/L → raw 720
        payload = struct.pack(">HH", 720, 0)
        response = _build_response(0x40, 0x03, payload)
        uart = _make_mock_uart(response)
        reader = SensorReader(uart)
        result = reader.read_do(address=0x40, name="do_sensor")
        assert abs(result["value"] - 7.20) < 0.01

class TestReadWaterLevel:
    def test_parses_level(self):
        # 8 registers: addr, baud, pressure_unit, decimal_places, level=85, range_min=0, range_max=200, extra
        payload = struct.pack(">HHHHHHHH", 0x31, 9600, 0, 0, 85, 0, 200, 0)
        response = _build_response(0x31, 0x03, payload)
        uart = _make_mock_uart(response)
        reader = SensorReader(uart)
        result = reader.read_water_level(address=0x31, name="wl_sensor")
        assert result["value"] == 85

    def test_parses_negative_level(self):
        # Two's complement: -5 = 0xFFFB
        payload = struct.pack(">HHHHHHHH", 0x31, 9600, 0, 0, 0xFFFB, 0, 200, 0)
        response = _build_response(0x31, 0x03, payload)
        uart = _make_mock_uart(response)
        reader = SensorReader(uart)
        result = reader.read_water_level(address=0x31, name="wl_sensor")
        assert result["value"] == -5

class TestBuildSensorJSON:
    def test_builds_ripple_compatible_json(self):
        reader = SensorReader(MagicMock())
        ph = {"value": 6.10, "temperature": 25.0}
        ec = {"value": 1.80, "tds": 0.90, "salinity": 0.99, "temperature": 25.0,
              "resistance": 1000.0, "ec_constant": 1.0, "compensation_coef": 0.02,
              "manual_temp": 25.0}
        wl = {"value": 85}
        relay_statuses = [0] * 16
        relay_map = {0: "NutrientPumpA", 1: "NutrientPumpB"}

        data = reader.build_sensor_json(
            ph_readings={"ph_sensor": ph},
            ec_readings={"ec_sensor": ec},
            do_readings=None,
            wl_readings={"wl_sensor": wl},
            relay_statuses=relay_statuses,
            relay_map=relay_map,
            timestamp_fn=lambda: "2026-01-31T12:00:00+0800"
        )

        assert "data" in data
        assert "water_metrics" in data["data"]
        assert "relay_metrics" in data["data"]
        assert "relays" in data
        # Check pH point format
        ph_points = data["data"]["water_metrics"]["ph"]["measurements"]["points"]
        assert len(ph_points) == 1
        assert ph_points[0]["tags"]["sensor"] == "ph"
        assert ph_points[0]["fields"]["value"] == 6.10
        # Check relay format
        assert data["relays"]["relayone"]["RELAYONE"]["RELAYONE"] == relay_statuses
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_sensors.py -v`
Expected: FAIL

**Step 3: Implement sensors.py**

```python
# sensors.py — Sensor reading via Modbus RTU and JSON formatting
import struct
from modbus_rtu import build_read_registers, parse_response, ModbusError

# MicroPython compat
try:
    import utime as time
except ImportError:
    import time


class SensorReader:
    """Reads sensors over a UART using Modbus RTU."""

    def __init__(self, uart, read_timeout_ms=500):
        self.uart = uart
        self.read_timeout_ms = read_timeout_ms

    def _send_and_receive(self, frame, expected_len):
        """Send Modbus frame and read response."""
        # Flush any stale data
        if hasattr(self.uart, 'any') and self.uart.any():
            self.uart.read()
        self.uart.write(frame)
        time.sleep(0.1)  # Wait for device to respond
        response = self.uart.read(expected_len)
        return response

    def read_ph(self, address, name):
        """Read pH and temperature from sensor."""
        frame = build_read_registers(address, 0x0000, 2)
        response = self._send_and_receive(frame, 9)
        if not response or len(response) < 9:
            return None
        try:
            parsed = parse_response(response)
            data = parsed["data"]
            ph_raw = (data[0] << 8) | data[1]
            temp_raw = (data[2] << 8) | data[3]
            return {"value": round(ph_raw / 100.0, 2), "temperature": round(temp_raw / 10.0, 1)}
        except (ModbusError, IndexError):
            return None

    def read_ec(self, address, name):
        """Read EC, TDS, salinity, temperature, etc."""
        frame = build_read_registers(address, 0x0000, 16)
        response = self._send_and_receive(frame, 37)
        if not response or len(response) < 37:
            return None
        try:
            parsed = parse_response(response)
            data = parsed["data"]
            # Parse byte-swapped 32-bit floats
            def parse_float(offset):
                raw = data[offset:offset + 4]
                if len(raw) < 4:
                    return 0.0
                swapped = bytes([raw[2], raw[3], raw[0], raw[1]])
                return round(struct.unpack(">f", swapped)[0], 2)

            ec = parse_float(0)
            resistance = parse_float(4)
            temperature = parse_float(8)
            tds = parse_float(12)
            salinity = parse_float(16)
            ec_constant = parse_float(20)
            comp_coef = parse_float(24)
            manual_temp = parse_float(28)

            return {
                "value": ec, "tds": tds, "salinity": salinity,
                "temperature": temperature, "resistance": resistance,
                "ec_constant": ec_constant, "compensation_coef": comp_coef,
                "manual_temp": manual_temp
            }
        except (ModbusError, IndexError, struct.error):
            return None

    def read_do(self, address, name):
        """Read dissolved oxygen value."""
        frame = build_read_registers(address, 0x0014, 2)
        response = self._send_and_receive(frame, 9)
        if not response or len(response) < 9:
            return None
        try:
            parsed = parse_response(response)
            data = parsed["data"]
            do_raw = (data[0] << 8) | data[1]
            return {"value": round(do_raw / 100.0, 2)}
        except (ModbusError, IndexError):
            return None

    def read_water_level(self, address, name):
        """Read water level (cm, signed int16)."""
        frame = build_read_registers(address, 0x0000, 8)
        response = self._send_and_receive(frame, 21)
        if not response or len(response) < 21:
            return None
        try:
            parsed = parse_response(response)
            data = parsed["data"]
            # Level is at register 4 (byte offset 8-9)
            level_raw = (data[8] << 8) | data[9]
            if level_raw > 32767:
                level_raw -= 65536
            return {"value": level_raw}
        except (ModbusError, IndexError):
            return None

    def build_sensor_json(self, ph_readings, ec_readings, do_readings,
                          wl_readings, relay_statuses, relay_map, timestamp_fn):
        """Build saved_sensor_data.json compatible with ripple-rpi format."""
        ts = timestamp_fn()
        data = {
            "data": {
                "water_metrics": {
                    "water_level": {"measurements": {"name": "water_metrics", "points": []}},
                    "ph": {"measurements": {"name": "water_metrics", "points": []}},
                    "ec": {"measurements": {"name": "water_metrics", "points": []}}
                },
                "relay_metrics": {
                    "measurements": {"name": "relay_metrics", "points": []},
                    "configuration": {
                        "relay_configuration": {
                            "relayone": {
                                "total_ports": 16,
                                "assigned_ports": sorted([int(k) for k in relay_map.keys()]),
                                "unassigned_ports": sorted([i for i in range(16) if i not in [int(k) for k in relay_map.keys()]])
                            }
                        }
                    }
                }
            },
            "relays": {
                "last_updated": ts,
                "relayone": {"RELAYONE": {"RELAYONE": list(relay_statuses)}}
            },
            "devices": {"last_updated": ts}
        }

        # Water level points
        if wl_readings:
            for name, reading in wl_readings.items():
                data["data"]["water_metrics"]["water_level"]["measurements"]["points"].append({
                    "tags": {"sensor": "water_level", "measurement": "level", "location": name},
                    "fields": {"value": reading["value"], "temperature": None, "pressure_unit": None,
                               "decimal_places": None, "range_min": 0, "range_max": 200, "zero_offset": None},
                    "timestamp": ts
                })

        # pH points
        if ph_readings:
            for name, reading in ph_readings.items():
                data["data"]["water_metrics"]["ph"]["measurements"]["points"].append({
                    "tags": {"sensor": "ph", "measurement": "ph", "location": name},
                    "fields": {"value": reading["value"], "temperature": reading.get("temperature", 25.0), "offset": None},
                    "timestamp": ts
                })

        # EC points
        if ec_readings:
            for name, reading in ec_readings.items():
                data["data"]["water_metrics"]["ec"]["measurements"]["points"].append({
                    "tags": {"sensor": "ec", "measurement": "ec", "location": name},
                    "fields": {
                        "value": reading["value"],
                        "tds": reading.get("tds", reading["value"] * 0.5),
                        "salinity": reading.get("salinity", reading["value"] * 0.55),
                        "temperature": reading.get("temperature", 25.0),
                        "resistance": reading.get("resistance", 1000.0),
                        "ec_constant": reading.get("ec_constant", 1.0),
                        "compensation_coef": reading.get("compensation_coef", 0.02),
                        "manual_temp": reading.get("manual_temp", 25.0),
                        "temp_offset": None, "electrode_sensitivity": None,
                        "compensation_mode": None, "sensor_type": None
                    },
                    "timestamp": ts
                })

        # Relay points
        for port, status in enumerate(relay_statuses):
            device_name = relay_map.get(port, relay_map.get(str(port), "none"))
            data["data"]["relay_metrics"]["measurements"]["points"].append({
                "tags": {
                    "relay_board": "relayone", "port_index": port,
                    "port_type": "assigned" if device_name != "none" else "unassigned",
                    "device": device_name
                },
                "fields": {"status": bool(status), "is_assigned": device_name != "none", "raw_status": bool(status)},
                "timestamp": ts
            })

        return data
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_sensors.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add sensors.py tests/test_sensors.py
git commit -m "feat: add sensor reader with Modbus RTU and ripple-compatible JSON builder"
```

---

### Task 4: Relay driver

**Files:**
- Create: `relay.py`
- Create: `tests/test_relay.py`

**Step 1: Write failing tests**

```python
# tests/test_relay.py
from unittest.mock import MagicMock
from modbus_rtu import crc16
from relay import RelayController

def _make_mock_uart(response_bytes):
    uart = MagicMock()
    uart.read = MagicMock(return_value=response_bytes)
    uart.write = MagicMock()
    uart.any = MagicMock(return_value=len(response_bytes) if response_bytes else 0)
    return uart

def _build_coil_status_response(statuses):
    """Build relay status response for 16 coils."""
    byte1 = 0
    byte2 = 0
    for i in range(min(8, len(statuses))):
        if statuses[i]:
            byte1 |= (1 << i)
    for i in range(8, min(16, len(statuses))):
        if statuses[i]:
            byte2 |= (1 << (i - 8))
    payload = bytes([0x01, 0x01, 0x02, byte1, byte2])
    return payload + crc16(payload)

class TestReadStatus:
    def test_all_off(self):
        response = _build_coil_status_response([0] * 16)
        uart = _make_mock_uart(response)
        ctrl = RelayController(uart, address=0x01)
        statuses = ctrl.read_status()
        assert statuses == [0] * 16

    def test_some_on(self):
        expected = [1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
        response = _build_coil_status_response(expected)
        uart = _make_mock_uart(response)
        ctrl = RelayController(uart, address=0x01)
        statuses = ctrl.read_status()
        assert statuses == expected

class TestWriteCoil:
    def test_turn_on_sends_correct_frame(self):
        # Echo response for write coil
        echo = bytes([0x01, 0x05, 0x00, 0x03, 0xFF, 0x00])
        echo += crc16(echo)
        uart = _make_mock_uart(echo)
        ctrl = RelayController(uart, address=0x01)
        result = ctrl.set_port(3, True)
        assert result is True
        # Verify the written frame
        written = uart.write.call_args[0][0]
        assert written[0] == 0x01
        assert written[1] == 0x05
        assert written[3] == 0x03
        assert written[4] == 0xFF

    def test_turn_off(self):
        echo = bytes([0x01, 0x05, 0x00, 0x03, 0x00, 0x00])
        echo += crc16(echo)
        uart = _make_mock_uart(echo)
        ctrl = RelayController(uart, address=0x01)
        result = ctrl.set_port(3, False)
        assert result is True

    def test_returns_false_on_no_response(self):
        uart = _make_mock_uart(None)
        ctrl = RelayController(uart, address=0x01)
        result = ctrl.set_port(3, True)
        assert result is False
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_relay.py -v`
Expected: FAIL

**Step 3: Implement relay.py**

```python
# relay.py — Relay board control via Modbus RTU
from modbus_rtu import build_read_coils, build_write_coil, parse_response, ModbusError

try:
    import utime as time
except ImportError:
    import time


class RelayController:
    """Controls a Modbus relay board (4/8/16 channel)."""

    def __init__(self, uart, address=0x01, num_ports=16):
        self.uart = uart
        self.address = address
        self.num_ports = num_ports
        self.statuses = [0] * num_ports

    def _send_and_receive(self, frame, expected_len):
        if hasattr(self.uart, 'any') and self.uart.any():
            self.uart.read()
        self.uart.write(frame)
        time.sleep(0.05)
        return self.uart.read(expected_len)

    def read_status(self):
        """Read all coil statuses. Returns list of 0/1."""
        frame = build_read_coils(self.address, 0x0000, self.num_ports)
        response = self._send_and_receive(frame, 7)
        if not response:
            return self.statuses
        try:
            parsed = parse_response(response)
            data = parsed["data"]
            statuses = []
            for byte_idx in range(len(data)):
                for bit in range(8):
                    if len(statuses) < self.num_ports:
                        statuses.append((data[byte_idx] >> bit) & 1)
            self.statuses = statuses
            return statuses
        except (ModbusError, IndexError):
            return self.statuses

    def set_port(self, port, on):
        """Turn a single relay port on or off. Returns True on success."""
        frame = build_write_coil(self.address, port, on)
        response = self._send_and_receive(frame, 8)
        if not response:
            return False
        try:
            parse_response(response)
            self.statuses[port] = 1 if on else 0
            return True
        except (ModbusError, IndexError):
            return False
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_relay.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add relay.py tests/test_relay.py
git commit -m "feat: add relay controller with read status and write coil"
```

---

### Task 5: Scheduler — cached schedule executor for autonomous mode

**Files:**
- Create: `scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write failing tests**

```python
# tests/test_scheduler.py
from scheduler import ScheduleCache, ScheduleEntry

class TestScheduleEntry:
    def test_is_due(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=True)
        # At t=0, should be due (never run)
        assert entry.is_due(current_s=0) is True

    def test_not_due_yet(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=True)
        entry.last_start_s = 100
        # 100s after last start, interval is 7200s
        assert entry.is_due(current_s=200) is False

    def test_due_after_interval(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=True)
        entry.last_start_s = 0
        assert entry.is_due(current_s=7201) is True

    def test_should_stop(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=True)
        entry.last_start_s = 100
        entry.running = True
        assert entry.should_stop(current_s=161) is True

    def test_should_not_stop_yet(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=True)
        entry.last_start_s = 100
        entry.running = True
        assert entry.should_stop(current_s=150) is False

    def test_disabled_never_due(self):
        entry = ScheduleEntry(name="pump_a", port=0, on_s=60, interval_s=7200, enabled=False)
        assert entry.is_due(current_s=99999) is False

class TestScheduleCache:
    def test_load_from_list(self):
        raw = [
            {"name": "pump_a", "port": 0, "on_s": 60, "interval_s": 7200, "enabled": True},
            {"name": "sprinkler", "port": 9, "on_s": 300, "interval_s": 3600, "enabled": True}
        ]
        cache = ScheduleCache()
        cache.load(raw)
        assert len(cache.entries) == 2
        assert cache.entries[0].name == "pump_a"

    def test_get_actions_returns_starts_and_stops(self):
        cache = ScheduleCache()
        cache.load([
            {"name": "pump_a", "port": 0, "on_s": 60, "interval_s": 7200, "enabled": True}
        ])
        actions = cache.get_actions(current_s=0)
        assert any(a["action"] == "on" for a in actions)

    def test_to_dict_and_from_dict(self):
        cache = ScheduleCache()
        cache.load([{"name": "pump_a", "port": 0, "on_s": 60, "interval_s": 7200, "enabled": True}])
        d = cache.to_dict()
        cache2 = ScheduleCache()
        cache2.from_dict(d)
        assert len(cache2.entries) == 1
        assert cache2.entries[0].name == "pump_a"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL

**Step 3: Implement scheduler.py**

```python
# scheduler.py — Cached schedule executor for autonomous mode


class ScheduleEntry:
    def __init__(self, name, port, on_s, interval_s, enabled=True):
        self.name = name
        self.port = port
        self.on_s = on_s
        self.interval_s = interval_s
        self.enabled = enabled
        self.last_start_s = None
        self.running = False

    def is_due(self, current_s):
        if not self.enabled:
            return False
        if self.running:
            return False
        if self.last_start_s is None:
            return True
        return (current_s - self.last_start_s) >= self.interval_s

    def should_stop(self, current_s):
        if not self.running or self.last_start_s is None:
            return False
        return (current_s - self.last_start_s) >= self.on_s

    def to_dict(self):
        return {
            "name": self.name, "port": self.port,
            "on_s": self.on_s, "interval_s": self.interval_s,
            "enabled": self.enabled, "last_start_s": self.last_start_s,
            "running": self.running
        }

    @classmethod
    def from_dict(cls, d):
        entry = cls(d["name"], d["port"], d["on_s"], d["interval_s"], d.get("enabled", True))
        entry.last_start_s = d.get("last_start_s")
        entry.running = d.get("running", False)
        return entry


class ScheduleCache:
    def __init__(self):
        self.entries = []

    def load(self, schedule_list):
        """Load schedule from list of dicts (from edge server)."""
        self.entries = [
            ScheduleEntry(
                name=s["name"], port=s["port"],
                on_s=s["on_s"], interval_s=s["interval_s"],
                enabled=s.get("enabled", True)
            )
            for s in schedule_list
        ]

    def get_actions(self, current_s):
        """Return list of actions to take now: [{"port": N, "action": "on"/"off", "name": "..."}]"""
        actions = []
        for entry in self.entries:
            if entry.should_stop(current_s):
                actions.append({"port": entry.port, "action": "off", "name": entry.name})
                entry.running = False
            if entry.is_due(current_s):
                actions.append({"port": entry.port, "action": "on", "name": entry.name})
                entry.last_start_s = current_s
                entry.running = True
        return actions

    def to_dict(self):
        return {"entries": [e.to_dict() for e in self.entries]}

    def from_dict(self, d):
        self.entries = [ScheduleEntry.from_dict(e) for e in d.get("entries", [])]
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_scheduler.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: add schedule cache for autonomous mode fallback"
```

---

### Task 6: Config manager — flash persistence

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests**

```python
# tests/test_config.py
import json
import os
import tempfile
from config import ConfigManager

class TestConfigManager:
    def test_load_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"device_id": "test-001", "edge_host": "192.168.1.1"}, f)
            f.flush()
            cfg = ConfigManager(config_path=f.name)
        assert cfg.get("device_id") == "test-001"
        os.unlink(f.name)

    def test_get_missing_returns_default(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            f.flush()
            cfg = ConfigManager(config_path=f.name)
        assert cfg.get("nonexistent", "fallback") == "fallback"
        os.unlink(f.name)

    def test_save_and_load_schedule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            schedule_path = os.path.join(tmpdir, "schedule_cache.json")
            with open(config_path, "w") as f:
                json.dump({}, f)
            cfg = ConfigManager(config_path=config_path, cache_dir=tmpdir)
            schedule = {"entries": [{"name": "pump", "port": 0, "on_s": 60, "interval_s": 3600, "enabled": True}]}
            cfg.save_schedule(schedule)
            loaded = cfg.load_schedule()
            assert loaded["entries"][0]["name"] == "pump"

    def test_load_schedule_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            with open(config_path, "w") as f:
                json.dump({}, f)
            cfg = ConfigManager(config_path=config_path, cache_dir=tmpdir)
            loaded = cfg.load_schedule()
            assert loaded is None
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_config.py -v`
Expected: FAIL

**Step 3: Implement config.py**

```python
# config.py — Configuration and flash persistence
import json
import os


class ConfigManager:
    def __init__(self, config_path="config.json", cache_dir="."):
        self.config_path = config_path
        self.cache_dir = cache_dir
        self._config = {}
        self._load()

    def _load(self):
        try:
            with open(self.config_path, "r") as f:
                self._config = json.load(f)
        except (OSError, ValueError):
            self._config = {}

    def get(self, key, default=None):
        return self._config.get(key, default)

    def save_schedule(self, schedule_dict):
        """Persist schedule cache to flash."""
        path = os.path.join(self.cache_dir, "schedule_cache.json") if self.cache_dir != "." else "schedule_cache.json"
        with open(path, "w") as f:
            json.dump(schedule_dict, f)

    def load_schedule(self):
        """Load cached schedule from flash. Returns None if not found."""
        path = os.path.join(self.cache_dir, "schedule_cache.json") if self.cache_dir != "." else "schedule_cache.json"
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_config.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add config.py tests/test_config.py
git commit -m "feat: add config manager with flash schedule persistence"
```

---

### Task 7: WebSocket client

**Files:**
- Create: `ws_client.py`
- Create: `tests/test_ws_client.py`

**Step 1: Write failing tests**

```python
# tests/test_ws_client.py
import json
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
from ws_client import EdgeWSClient

class TestMessageBuilding:
    def test_build_heartbeat(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.device_id = "test-001"
        client.api_version = "1.0.0"
        msg = client._build_heartbeat("2026-01-31T12:00:00+0800")
        assert msg["type"] == "heartbeat"
        assert msg["device_id"] == "test-001"
        assert msg["version"] == "1.0.0"

    def test_build_device_data(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.device_id = "test-001"
        client.api_version = "1.0.0"
        sensor_data = {"data": {"water_metrics": {}}}
        msg = client._build_device_data(sensor_data, "2026-01-31T12:00:00+0800")
        assert msg["type"] == "device_data"
        assert msg["data"] == sensor_data

    def test_build_command_response(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.device_id = "test-001"
        msg = client._build_command_response("cmd-123", True, "Relay on")
        assert msg["type"] == "device_command_response"
        assert msg["command_id"] == "cmd-123"
        assert msg["success"] is True

class TestCommandParsing:
    def test_parse_relay_command(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.relay_name_to_port = {"NutrientPumpA": 0, "SprinklerA": 9}
        msg = {"type": "device_command", "command_id": "cmd-1", "command": "NutrientPumpA", "params": {"state": True}}
        result = client._parse_command(msg)
        assert result["port"] == 0
        assert result["on"] is True
        assert result["command_id"] == "cmd-1"

    def test_parse_relay_command_with_duration(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.relay_name_to_port = {"SprinklerA": 9}
        msg = {"type": "device_command", "command_id": "cmd-2", "command": "SprinklerA", "params": {"state": True, "duration_s": 300}}
        result = client._parse_command(msg)
        assert result["port"] == 9
        assert result["duration_s"] == 300

    def test_parse_time_sync(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        msg = {"type": "time_sync", "utc": 1706659200}
        result = client._parse_command(msg)
        assert result["type"] == "time_sync"
        assert result["utc"] == 1706659200

    def test_parse_schedule_update(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        schedule = [{"name": "pump_a", "port": 0, "on_s": 60, "interval_s": 7200, "enabled": True}]
        msg = {"type": "schedule_update", "schedule": schedule}
        result = client._parse_command(msg)
        assert result["type"] == "schedule_update"
        assert len(result["schedule"]) == 1

    def test_unknown_command_returns_none(self):
        client = EdgeWSClient.__new__(EdgeWSClient)
        client.relay_name_to_port = {}
        msg = {"type": "device_command", "command_id": "cmd-3", "command": "UnknownDevice", "params": {}}
        result = client._parse_command(msg)
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_ws_client.py -v`
Expected: FAIL

**Step 3: Implement ws_client.py**

```python
# ws_client.py — WebSocket client for communicating with lumina-edge
import json

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class EdgeWSClient:
    """WebSocket client that connects to lumina-edge local device server."""

    def __init__(self, host, port, device_id, device_secret, relay_port_map):
        self.host = host
        self.port = port
        self.device_id = device_id
        self.device_secret = device_secret
        self.api_version = "1.0.0"
        self.ws = None
        self.connected = False
        self._on_command = None  # callback: async def handler(parsed_cmd)
        self._on_time_sync = None
        self._on_schedule_update = None
        # Build reverse map: device_name -> port_index
        self.relay_name_to_port = {}
        for port_str, name in relay_port_map.items():
            self.relay_name_to_port[name] = int(port_str)

    def on_command(self, handler):
        self._on_command = handler

    def on_time_sync(self, handler):
        self._on_time_sync = handler

    def on_schedule_update(self, handler):
        self._on_schedule_update = handler

    def _build_heartbeat(self, timestamp):
        return {
            "type": "heartbeat",
            "device_id": self.device_id,
            "timestamp": timestamp,
            "version": self.api_version
        }

    def _build_device_data(self, sensor_data, timestamp):
        return {
            "type": "device_data",
            "device_id": self.device_id,
            "version": self.api_version,
            "time": timestamp,
            "data": sensor_data
        }

    def _build_command_response(self, command_id, success, message=""):
        return {
            "type": "device_command_response",
            "command_id": command_id,
            "success": success,
            "message": message
        }

    def _parse_command(self, msg):
        """Parse incoming message from edge. Returns parsed dict or None."""
        msg_type = msg.get("type")

        if msg_type == "time_sync":
            return {"type": "time_sync", "utc": msg["utc"]}

        if msg_type == "schedule_update":
            return {"type": "schedule_update", "schedule": msg["schedule"]}

        if msg_type == "device_command":
            command_name = msg.get("command", "")
            params = msg.get("params", {})
            command_id = msg.get("command_id", "")
            port = self.relay_name_to_port.get(command_name)
            if port is None:
                return None
            return {
                "type": "relay_command",
                "command_id": command_id,
                "port": port,
                "on": bool(params.get("state", False)),
                "duration_s": params.get("duration_s", 0)
            }

        return None

    async def connect(self):
        """Connect to lumina-edge WebSocket server."""
        url = f"ws://{self.host}:{self.port}/ws/device?device_id={self.device_id}&device_secret={self.device_secret}"
        try:
            # MicroPython: use uasyncio websocket or aiohttp
            # Desktop: use websockets library
            import websockets
            self.ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    async def send(self, msg_dict):
        """Send a JSON message."""
        if not self.connected or not self.ws:
            return False
        try:
            await self.ws.send(json.dumps(msg_dict))
            return True
        except Exception:
            self.connected = False
            return False

    async def send_heartbeat(self, timestamp):
        return await self.send(self._build_heartbeat(timestamp))

    async def send_device_data(self, sensor_data, timestamp):
        return await self.send(self._build_device_data(sensor_data, timestamp))

    async def send_command_response(self, command_id, success, message=""):
        return await self.send(self._build_command_response(command_id, success, message))

    async def listen(self):
        """Listen for messages from edge. Dispatches to registered handlers."""
        if not self.ws:
            return
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                parsed = self._parse_command(msg)
                if parsed is None:
                    continue
                if parsed["type"] == "time_sync" and self._on_time_sync:
                    await self._on_time_sync(parsed)
                elif parsed["type"] == "schedule_update" and self._on_schedule_update:
                    await self._on_schedule_update(parsed)
                elif parsed["type"] == "relay_command" and self._on_command:
                    await self._on_command(parsed)
        except Exception:
            self.connected = False

    async def disconnect(self):
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.connected = False
```

**Step 4: Run tests**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/test_ws_client.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd ~/dev/ripple-esp
git add ws_client.py tests/test_ws_client.py
git commit -m "feat: add WebSocket client for lumina-edge communication"
```

---

### Task 8: Main loop — state machine and uasyncio orchestration

**Files:**
- Modify: `main.py`

**Step 1: Implement the full main.py state machine**

```python
# main.py — uasyncio entry point, state machine
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

import json
import time as _time

from config import ConfigManager
from sensors import SensorReader
from relay import RelayController
from ws_client import EdgeWSClient
from scheduler import ScheduleCache

# States
BOOT = "BOOT"
CONNECTING = "CONNECTING"
SYNCING = "SYNCING"
PASSIVE = "PASSIVE"
AUTONOMOUS = "AUTONOMOUS"


class RippleESP:
    def __init__(self):
        self.state = BOOT
        self.cfg = None
        self.sensor_reader = None
        self.relay_ctrl = None
        self.ws = None
        self.schedule = ScheduleCache()
        self.rtc_offset = 0  # UTC epoch offset from boot time
        self.boot_time_s = 0
        self.last_ws_message_s = 0
        self.sensor_buffer = []  # Buffer readings when disconnected
        self.relay_port_map = {}
        self.timed_relays = {}  # port -> stop_time for duration-based commands

    def now_s(self):
        """Current time in seconds since epoch (approximated via RTC offset)."""
        return int(_time.time()) if self.rtc_offset == 0 else self.rtc_offset + (int(_time.time()) - self.boot_time_s)

    def timestamp(self):
        """ISO 8601 timestamp with UTC offset."""
        t = self.now_s()
        utc_offset = self.cfg.get("utc_offset_hours", 8)
        t_local = t + utc_offset * 3600
        # Format manually for MicroPython compatibility
        try:
            from time import gmtime
            tm = gmtime(t_local)
            return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}+{:02d}00".format(
                tm[0], tm[1], tm[2], tm[3], tm[4], tm[5], utc_offset)
        except Exception:
            return str(t)

    async def boot(self):
        """Initialize hardware and load config."""
        self.cfg = ConfigManager()
        self.boot_time_s = int(_time.time())

        # Load cached schedule
        cached = self.cfg.load_schedule()
        if cached:
            self.schedule.from_dict(cached)

        # Relay port map
        self.relay_port_map = self.cfg.get("relay_port_map", {})

        # Init UARTs — on real hardware, use machine.UART
        try:
            from machine import UART
            sensor_uart = UART(1, baudrate=9600,
                               tx=self.cfg.get("sensor_uart_tx", 17),
                               rx=self.cfg.get("sensor_uart_rx", 18))
            relay_uart = UART(2, baudrate=38400,
                              tx=self.cfg.get("relay_uart_tx", 15),
                              rx=self.cfg.get("relay_uart_rx", 16))
        except ImportError:
            # Desktop testing — skip UART init
            sensor_uart = None
            relay_uart = None

        if sensor_uart:
            self.sensor_reader = SensorReader(sensor_uart)
        if relay_uart:
            self.relay_ctrl = RelayController(relay_uart, address=self.cfg.get("relay_address", 1))

        # Init WebSocket client
        self.ws = EdgeWSClient(
            host=self.cfg.get("edge_host", "192.168.1.100"),
            port=self.cfg.get("edge_port", 9090),
            device_id=self.cfg.get("device_id", "ripple-esp-001"),
            device_secret=self.cfg.get("device_secret", ""),
            relay_port_map=self.relay_port_map
        )
        self.ws.on_command(self._handle_relay_command)
        self.ws.on_time_sync(self._handle_time_sync)
        self.ws.on_schedule_update(self._handle_schedule_update)

        self.state = CONNECTING

    async def _handle_relay_command(self, cmd):
        """Handle relay on/off command from edge."""
        port = cmd["port"]
        on = cmd["on"]
        duration_s = cmd.get("duration_s", 0)
        success = False
        if self.relay_ctrl:
            success = self.relay_ctrl.set_port(port, on)
            if success and on and duration_s > 0:
                self.timed_relays[port] = self.now_s() + duration_s
        await self.ws.send_command_response(cmd["command_id"], success,
                                            f"Relay {port} {'on' if on else 'off'}")

    async def _handle_time_sync(self, cmd):
        """Sync RTC from edge server."""
        self.rtc_offset = cmd["utc"]
        self.boot_time_s = int(_time.time())
        self.last_ws_message_s = self.now_s()

    async def _handle_schedule_update(self, cmd):
        """Update and cache schedule from edge."""
        self.schedule.load(cmd["schedule"])
        self.cfg.save_schedule(self.schedule.to_dict())
        self.last_ws_message_s = self.now_s()

    def _read_all_sensors(self):
        """Read all sensors and return dicts keyed by sensor name."""
        if not self.sensor_reader:
            return None, None, None, None
        sensors = self.cfg.get("sensors", {})
        ph = ec = do = wl = None
        if "ph" in sensors:
            s = sensors["ph"]
            result = self.sensor_reader.read_ph(s["address"], s["name"])
            if result:
                ph = {s["name"]: result}
        if "ec" in sensors:
            s = sensors["ec"]
            result = self.sensor_reader.read_ec(s["address"], s["name"])
            if result:
                ec = {s["name"]: result}
        if "do" in sensors:
            s = sensors["do"]
            result = self.sensor_reader.read_do(s["address"], s["name"])
            if result:
                do = {s["name"]: result}
        if "water_level" in sensors:
            s = sensors["water_level"]
            result = self.sensor_reader.read_water_level(s["address"], s["name"])
            if result:
                wl = {s["name"]: result}
        return ph, ec, do, wl

    async def _poll_and_report(self):
        """Read sensors, build JSON, send to edge or buffer."""
        ph, ec, do, wl = self._read_all_sensors()
        relay_statuses = self.relay_ctrl.read_status() if self.relay_ctrl else [0] * 16
        sensor_json = self.sensor_reader.build_sensor_json(
            ph_readings=ph, ec_readings=ec, do_readings=do,
            wl_readings=wl, relay_statuses=relay_statuses,
            relay_map=self.relay_port_map, timestamp_fn=self.timestamp
        ) if self.sensor_reader else {}

        if self.ws and self.ws.connected:
            # Flush buffer first
            for buffered in self.sensor_buffer:
                await self.ws.send_device_data(buffered, self.timestamp())
            self.sensor_buffer.clear()
            await self.ws.send_device_data(sensor_json, self.timestamp())
            self.last_ws_message_s = self.now_s()
        else:
            if len(self.sensor_buffer) < 100:
                self.sensor_buffer.append(sensor_json)

    async def _check_timed_relays(self):
        """Turn off relays whose duration has expired."""
        now = self.now_s()
        expired = [p for p, stop_t in self.timed_relays.items() if now >= stop_t]
        for port in expired:
            if self.relay_ctrl:
                self.relay_ctrl.set_port(port, False)
            del self.timed_relays[port]

    async def run(self):
        """Main event loop."""
        await self.boot()
        poll_interval = self.cfg.get("sensor_poll_s", 30)
        heartbeat_interval = self.cfg.get("heartbeat_s", 20)
        autonomous_timeout = self.cfg.get("autonomous_timeout_s", 30)
        reconnect_delay = 1

        last_poll = 0
        last_heartbeat = 0

        while True:
            now = self.now_s()

            if self.state == CONNECTING:
                success = await self.ws.connect()
                if success:
                    self.state = SYNCING
                    reconnect_delay = 1
                else:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
                    # While connecting, run autonomous if we have a schedule
                    if self.schedule.entries:
                        self.state = AUTONOMOUS
                continue

            if self.state == SYNCING:
                # The edge will send time_sync and schedule on connect
                # Start listening — handlers will process sync messages
                asyncio.create_task(self.ws.listen())
                # Wait briefly for sync messages
                await asyncio.sleep(2)
                self.state = PASSIVE
                continue

            # Sensor polling
            if now - last_poll >= poll_interval:
                await self._poll_and_report()
                last_poll = now

            # Heartbeat
            if self.state == PASSIVE and now - last_heartbeat >= heartbeat_interval:
                if self.ws and self.ws.connected:
                    await self.ws.send_heartbeat(self.timestamp())
                    last_heartbeat = now

            # Check timed relay expirations
            await self._check_timed_relays()

            # Connection watchdog
            if self.state == PASSIVE and not self.ws.connected:
                if now - self.last_ws_message_s > autonomous_timeout:
                    self.state = AUTONOMOUS

            # Autonomous mode — execute cached schedule
            if self.state == AUTONOMOUS:
                uptime = now - self.boot_time_s if self.rtc_offset == 0 else now
                actions = self.schedule.get_actions(uptime)
                for action in actions:
                    if self.relay_ctrl:
                        self.relay_ctrl.set_port(action["port"], action["action"] == "on")
                # Try to reconnect
                if await self.ws.connect():
                    self.state = SYNCING
                    continue

            await asyncio.sleep(1)


def main():
    app = RippleESP()
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
```

**Step 2: Run all existing tests to verify nothing broke**

Run: `cd ~/dev/ripple-esp && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd ~/dev/ripple-esp
git add main.py boot.py
git commit -m "feat: add main state machine with passive/autonomous hybrid control"
```

---

### Task 9: lumina-edge API plan

**Files:**
- Create: `~/dev/lumina-edge/docs/plans/2026-01-31-esp32-websocket-integration.md`

This is a **design document only** — no code changes to lumina-edge in this plan.

**Step 1: Write the API plan**

The plan should document what lumina-edge needs to support:

1. **New message types to send to ESP32 devices:**
   - `time_sync` — sent on device connect and every 5 minutes
   - `schedule_update` — sent on device connect and when instruction set changes

2. **New message types to receive from ESP32 devices:**
   - `device_data` — already handled by `handle_device_data()` in `local_device_server.py`
   - `heartbeat` — already handled
   - `device_command_response` — already handled by `handle_device_response()`

3. **Modifications needed in `local_device_server.py`:**
   - After device WebSocket connection established: send `time_sync` message
   - After device WebSocket connection established: send current fertigation schedule as `schedule_update`
   - When instruction set changes: push `schedule_update` to connected ESP32 devices
   - Route fertigation relay commands to ESP32 via WebSocket instead of REST to Ripple

4. **Fertigation subsystem change:**
   - New `WebSocketFertigation` class (alongside existing `RestFertigation`)
   - Instead of HTTP GET/POST to Ripple, sends `device_command` via WebSocket to ESP32
   - Reads sensor data from `device_data` messages instead of polling REST API
   - Register in `FertigationFactory` as model type `ESP32`

5. **Config change in `device.conf`:**
   ```ini
   [SYSTEM]
   fertigation_model = ESP32
   fertigation_device_id = ripple-esp-001
   ```

**Step 2: Commit** (in lumina-edge repo)

```bash
cd ~/dev/lumina-edge
git add docs/plans/2026-01-31-esp32-websocket-integration.md
git commit -m "docs: add ESP32 WebSocket integration API plan"
```

---

## Summary

| Task | Component | Key Output |
|------|-----------|------------|
| 1 | Repo skeleton | `config.json`, `boot.py`, `main.py` stubs |
| 2 | Modbus RTU | CRC-16, frame builder, response parser |
| 3 | Sensors | pH, EC, DO, WaterLevel + ripple-compatible JSON builder |
| 4 | Relay | Read status, write coil |
| 5 | Scheduler | Cached schedule with interval-based executor |
| 6 | Config | Flash persistence for schedule cache |
| 7 | WebSocket | Client with message build/parse for lumina-edge protocol |
| 8 | Main loop | State machine: BOOT→CONNECTING→SYNCING→PASSIVE↔AUTONOMOUS |
| 9 | lumina-edge plan | API design doc for ESP32 WebSocket integration |
