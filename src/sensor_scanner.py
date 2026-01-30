"""
SensorScanner — auto-detect Modbus sensors by probing addresses.

Iterates over ports, baud rates, and slave addresses, attempting type-specific
register reads and validating responses to identify connected sensors.
"""

import logging
import math
import struct
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── defaults ────────────────────────────────────────────────────────────────
DEFAULT_PORTS = ['/dev/ttyAMA1', '/dev/ttyAMA2', '/dev/ttyAMA3']
DEFAULT_BAUD_RATES = [4800, 9600, 38400]
DEFAULT_ADDR_START = 0x00
DEFAULT_ADDR_END = 0x99
DEFAULT_SENSOR_TYPES = ['ec', 'water_level', 'ph', 'do']

# Per-type probe parameters: (register_address, register_count, timeout)
PROBE_PARAMS: Dict[str, dict] = {
    'ph':          {'register': 0x0000, 'count': 2,  'timeout': 0.5},
    'do':          {'register': 0x0014, 'count': 2,  'timeout': 0.5},
    'ec':          {'register': 0x0000, 'count': 16, 'timeout': 0.8},
    'water_level': {'register': 0x0000, 'count': 8,  'timeout': 0.8},
}

INTER_PROBE_DELAY = 0.05  # seconds between probes at the same address


class SensorScanner:
    """Scan Modbus bus for connected sensors."""

    def __init__(
        self,
        modbus_client,
        ports: Optional[List[str]] = None,
        baud_rates: Optional[List[int]] = None,
        addr_start: int = DEFAULT_ADDR_START,
        addr_end: int = DEFAULT_ADDR_END,
        sensor_types: Optional[List[str]] = None,
        short_circuit: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.client = modbus_client
        self.ports = ports if ports is not None else list(DEFAULT_PORTS)
        self.baud_rates = baud_rates if baud_rates is not None else list(DEFAULT_BAUD_RATES)
        self.addr_start = addr_start
        self.addr_end = addr_end
        self.sensor_types = sensor_types if sensor_types is not None else list(DEFAULT_SENSOR_TYPES)
        self.short_circuit = short_circuit
        self.on_progress = on_progress

    # ── public API ──────────────────────────────────────────────────────────

    def scan(self) -> List[Dict[str, Any]]:
        """Scan all configured ports/baud/addresses and return found sensors."""
        results: List[Dict[str, Any]] = []

        for port in self.ports:
            for baud in self.baud_rates:
                for addr in range(self.addr_start, self.addr_end + 1):
                    found = self._probe_address(port, baud, addr)
                    if found is not None:
                        metadata = {
                            'port': port,
                            'baud_rate': baud,
                            'address': f'0x{addr:02x}',
                            'address_decimal': addr,
                        }
                        if isinstance(found, list):
                            for item in found:
                                item.update(metadata)
                                results.append(item)
                        else:
                            found.update(metadata)
                            results.append(found)

                    if self.on_progress is not None:
                        self.on_progress({
                            'port': port,
                            'baud_rate': baud,
                            'address': f'0x{addr:02x}',
                            'found': found is not None,
                        })

        return results

    # ── internal ────────────────────────────────────────────────────────────

    def _probe_address(self, port: str, baud: int, addr: int):
        """Probe a single address with each sensor type.

        Returns:
            A single result dict if short_circuit is True and a match is found,
            a list of result dicts if short_circuit is False,
            or None if nothing matched.
        """
        matches: List[Dict[str, Any]] = []

        for idx, sensor_type in enumerate(self.sensor_types):
            if idx > 0:
                time.sleep(INTER_PROBE_DELAY)

            result = self._run_probe(port, baud, addr, sensor_type)
            if result is not None:
                if self.short_circuit:
                    return result
                matches.append(result)

        if not self.short_circuit and matches:
            return matches
        return None

    def _run_probe(self, port: str, baud: int, addr: int, sensor_type: str):
        """Execute a single type-specific probe and validate the response.

        Returns a result dict on success, None on failure.
        """
        params = PROBE_PARAMS.get(sensor_type)
        if params is None:
            return None

        try:
            response = self.client.read_holding_registers(
                port,
                params['register'],
                params['count'],
                addr,
                baudrate=baud,
                timeout=params['timeout'],
                device_name=f'scan_{sensor_type}',
            )
        except Exception:
            logger.debug("Probe %s@0x%02X on %s/%d raised exception", sensor_type, addr, port, baud)
            return None

        if response is None or response.isError():
            return None

        if not hasattr(response, 'registers') or response.registers is None:
            return None

        if len(response.registers) < params['count']:
            return None

        validator = {
            'ph': self._validate_ph,
            'do': self._validate_do,
            'ec': self._validate_ec,
            'water_level': self._validate_water_level,
        }.get(sensor_type)

        if validator is None:
            return None

        return validator(response.registers)

    # ── validators ──────────────────────────────────────────────────────────

    @staticmethod
    def _validate_ph(registers) -> Optional[Dict[str, Any]]:
        """Validate pH sensor response: 2 regs at 0x0000.

        reg[0] = ph_raw  (0–1400 → pH 0.00–14.00)
        reg[1] = temp_raw (0–1200 → temp 0.0–120.0 C)
        """
        ph_raw = registers[0]
        temp_raw = registers[1]

        if not (0 <= ph_raw <= 1400):
            return None
        if not (0 <= temp_raw <= 1200):
            return None

        return {
            'sensor_type': 'ph',
            'sample_reading': {
                'ph': ph_raw / 100.0,
                'temperature': temp_raw / 10.0,
            },
        }

    @staticmethod
    def _validate_do(registers) -> Optional[Dict[str, Any]]:
        """Validate dissolved-oxygen sensor response: 2 regs at 0x0014.

        reg[0] = do_raw (1–2000 → DO 0.01–20.00 mg/L)
        """
        do_raw = registers[0]

        if not (1 <= do_raw <= 2000):
            return None

        return {
            'sensor_type': 'do',
            'sample_reading': {
                'do': do_raw / 100.0,
            },
        }

    @staticmethod
    def _validate_ec(registers) -> Optional[Dict[str, Any]]:
        """Validate EC sensor response: 16 regs at 0x0000.

        First two registers encode a float in byte-reordered form:
        [lo_word, hi_word] → pack('>HH', hi, lo) → unpack('>f')
        EC value must be 0–200 and not NaN/Inf.
        """
        lo_word = registers[0]
        hi_word = registers[1]

        try:
            raw_bytes = struct.pack('>HH', hi_word, lo_word)
            value = struct.unpack('>f', raw_bytes)[0]
        except (struct.error, OverflowError):
            return None

        if math.isnan(value) or math.isinf(value):
            return None
        if not (0 <= value <= 200):
            return None

        return {
            'sensor_type': 'ec',
            'sample_reading': {
                'ec': value,
            },
        }

    @staticmethod
    def _validate_water_level(registers) -> Optional[Dict[str, Any]]:
        """Validate water-level sensor response: 8 regs at 0x0000.

        reg[2] = unit       (9–17)
        reg[3] = decimal    (0–3)
        reg[4] = level      (signed 16-bit)
        reg[5] = range_min
        reg[6] = range_max
        range_min <= range_max required.
        """
        unit = registers[2]
        decimal = registers[3]
        level = registers[4]
        range_min = registers[5]
        range_max = registers[6]

        # Signed 16-bit conversion for level
        if level > 0x7FFF:
            level = level - 0x10000

        if not (9 <= unit <= 17):
            return None
        if not (0 <= decimal <= 3):
            return None
        if range_min > range_max:
            return None

        return {
            'sensor_type': 'water_level',
            'sample_reading': {
                'level': level,
                'unit': 'cm',
                'range_min': range_min,
                'range_max': range_max,
            },
        }


# ── output formatting ────────────────────────────────────────────────────────

SENSOR_DISPLAY_NAMES = {
    'ph': 'pH',
    'ec': 'EC',
    'do': 'DO',
    'water_level': 'Water Level',
}

SENSOR_DESCRIPTIONS = {
    'ph': 'pH Sensor',
    'ec': 'EC Sensor',
    'do': 'DO Sensor',
    'water_level': 'Water Level Sensor',
}


def _format_sample(sensor_type, reading):
    """Format sample reading for display."""
    if sensor_type == 'ph':
        parts = []
        if 'ph' in reading:
            parts.append(f"pH={reading['ph']:.2f}")
        if 'temperature' in reading:
            parts.append(f"Temp={reading['temperature']:.1f}\u00b0C")
        return '  '.join(parts)
    elif sensor_type == 'ec':
        return f"EC={reading['ec']:.3f} mS/cm" if 'ec' in reading else ''
    elif sensor_type == 'do':
        return f"DO={reading['do']:.2f} mg/L" if 'do' in reading else ''
    elif sensor_type == 'water_level':
        return f"Level={reading['level']} cm" if 'level' in reading else ''
    return ''


def format_results(results):
    """Format scan results as a readable table."""
    if not results:
        return 'No sensors found.'

    lines = [f'Found {len(results)} sensor(s):']
    for r in results:
        name = SENSOR_DISPLAY_NAMES.get(r['sensor_type'], r['sensor_type'])
        sample = _format_sample(r['sensor_type'], r.get('sample_reading', {}))
        lines.append(
            f"  {name:<12} {r['port']:<16} {r['address']:<6} {r['baud_rate']:<6} {sample}"
        )
    return '\n'.join(lines)


def format_device_conf(results):
    """Generate suggested device.conf [SENSORS] entries."""
    if not results:
        return ''

    type_counts = {}
    lines = ['Suggested device.conf [SENSORS] entries:']

    for r in results:
        stype = r['sensor_type']
        count = type_counts.get(stype, 0)
        type_counts[stype] = count + 1
        position = 'main' if count == 0 else f'secondary_{count}'
        desc = SENSOR_DESCRIPTIONS.get(stype, stype)
        key = f'{stype}_{position}'
        lines.append(
            f'  {key} = {stype}, {position}, "{desc}", {r["port"]}, {r["address"]}, {r["baud_rate"]}'
        )

    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    import sys
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    import src.globals as globals

    parser = argparse.ArgumentParser(description='Scan for Modbus sensors')
    parser.add_argument('--ports', nargs='+', default=DEFAULT_PORTS,
                        help='Serial ports to scan')
    parser.add_argument('--baud-rates', nargs='+', type=int, default=DEFAULT_BAUD_RATES,
                        help='Baud rates to try')
    parser.add_argument('--addr-start', type=lambda x: int(x, 0), default=DEFAULT_ADDR_START,
                        help='Start address (hex or decimal)')
    parser.add_argument('--addr-end', type=lambda x: int(x, 0), default=DEFAULT_ADDR_END,
                        help='End address (hex or decimal)')
    parser.add_argument('--types', nargs='+', default=DEFAULT_SENSOR_TYPES,
                        choices=DEFAULT_SENSOR_TYPES, help='Sensor types to scan for')
    parser.add_argument('--no-short-circuit', action='store_true',
                        help='Try all probes per address even after a match')

    args = parser.parse_args()

    def print_progress(info):
        sys.stdout.write(
            f"\rScanning {info['port']} @ {info['baud_rate']} baud — addr {info['address']}"
        )
        sys.stdout.flush()

    scanner = SensorScanner(
        modbus_client=globals.modbus_client,
        ports=args.ports,
        baud_rates=args.baud_rates,
        addr_start=args.addr_start,
        addr_end=args.addr_end,
        sensor_types=args.types,
        short_circuit=not args.no_short_circuit,
        on_progress=print_progress,
    )

    print('Starting sensor scan...')
    start_time = time.time()
    results = scanner.scan()
    duration = time.time() - start_time

    print(f'\n\nScan completed in {duration:.1f}s\n')
    print(format_results(results))
    if results:
        print()
        print(format_device_conf(results))
