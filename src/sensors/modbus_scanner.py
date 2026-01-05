#!/usr/bin/env python3
"""
Modbus Device Scanner

Scans through multiple serial ports, baud rates, and addresses to identify
connected Modbus devices. Attempts to identify device types based on response
patterns and value ranges.

Supports parallel port scanning for faster results.

Usage:
    python modbus_scanner.py [--ports ttyAMA1,ttyAMA2] [--bauds 9600,38400] [--addresses 0x01-0xFF]
"""

import time
import os
import sys
import struct
import argparse
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Add the project root and src directory to Python path
current_dir = os.path.dirname(__file__)
project_root = os.path.dirname(os.path.dirname(current_dir))
src_dir = os.path.join(project_root, 'src')
sys.path.insert(0, project_root)
sys.path.insert(0, src_dir)

# Import lumina modbus client for TCP bridge communication
try:
    from lumina_modbus_client import LuminaModbusClient
    from lumina_logger import GlobalLogger
    USING_TCP_BRIDGE = True
except ImportError as e:
    USING_TCP_BRIDGE = False
    print(f"Warning: Could not import LuminaModbusClient: {e}")
    print("Make sure lumina-modbus-server is running and you're running from the project root.")


logger = GlobalLogger("ModbusScanner", log_prefix="scanner_").logger if USING_TCP_BRIDGE else None


class ModbusScanner:
    """
    Scans for Modbus devices across multiple ports, baud rates, and addresses.

    Identifies device types based on:
    - Response patterns and register maps
    - Value ranges (pH: 3-10, EC: 0-3, DO: 0-20, Water Level: 0-100)
    - Communication characteristics (relays typically at 38400 baud)
    """

    # Device type detection patterns
    DEVICE_PATTERNS = {
        'pH': {
            'register': 0x0000,
            'count': 2,
            'typical_bauds': [9600, 4800],
            'value_check': lambda vals: 0 <= vals[0] / 100.0 <= 14,
            'value_format': lambda vals: f"pH: {vals[0] / 100.0:.2f}, Temp: {vals[1] / 10.0:.1f}°C"
        },
        'EC': {
            'register': 0x0000,
            'count': 16,
            'typical_bauds': [9600, 4800],
            'value_check': lambda vals: 0 <= vals[0] <= 5.0,  # EC in mS/cm
            'value_format': lambda vals: f"EC: {vals[0]:.3f} mS/cm"
        },
        'DO': {
            'register': 0x0014,
            'count': 2,
            'typical_bauds': [9600, 4800],
            'value_check': lambda vals: 0 <= vals[0] / 100.0 <= 25,
            'value_format': lambda vals: f"DO: {vals[0] / 100.0:.2f} mg/L"
        },
        'Water_Level': {
            'register': 0x0004,
            'count': 1,
            'typical_bauds': [9600, 4800],
            'value_check': lambda vals: -100 <= vals[0] <= 500,  # cm
            'value_format': lambda vals: f"Level: {vals[0]} cm"
        },
        'Relay': {
            'register': 0x0000,
            'count': 1,
            'typical_bauds': [38400],
            'value_check': lambda vals: True,  # Relays have different protocol
            'value_format': lambda vals: f"Relay status: 0x{vals[0]:02X}"
        }
    }

    def __init__(self):
        """Initialize the scanner with Modbus client."""
        if USING_TCP_BRIDGE:
            self.modbus_client = LuminaModbusClient()
            # Connect to the modbus server
            if not self.modbus_client.connect():
                print("ERROR: Could not connect to Modbus server at 127.0.0.1:8888")
                print("Make sure lumina-modbus-server is running.")
                sys.exit(1)
        else:
            print("ERROR: LuminaModbusClient not available. Cannot scan.")
            sys.exit(1)

        self.found_devices = []
        self.devices_lock = Lock()  # Thread-safe access to found_devices
        self.progress_lock = Lock()  # Thread-safe progress updates

    def scan(
        self,
        ports: List[str] = None,
        baud_rates: List[int] = None,
        address_range: Tuple[int, int] = (0x01, 0xFF),
        timeout: float = 0.5,
        parallel: bool = True
    ):
        """
        Scan for Modbus devices.

        Args:
            ports: List of serial ports to scan (e.g., ['ttyAMA1', 'ttyAMA2'])
            baud_rates: List of baud rates to try (e.g., [4800, 9600, 38400])
            address_range: Tuple of (start_addr, end_addr) to scan
            timeout: Timeout for each read attempt in seconds
            parallel: Whether to scan ports in parallel (default: True)
        """
        if ports is None:
            ports = ['ttyAMA1', 'ttyAMA2', 'ttyAMA3', 'ttyAMA4']

        if baud_rates is None:
            baud_rates = [4800, 9600, 38400]

        start_addr, end_addr = address_range
        total_attempts = len(ports) * len(baud_rates) * (end_addr - start_addr + 1)

        print(f"\n{'='*70}")
        print(f"Modbus Device Scanner")
        print(f"{'='*70}")
        print(f"Scanning {len(ports)} ports × {len(baud_rates)} baud rates × {end_addr - start_addr + 1} addresses")
        print(f"Total attempts: {total_attempts}")
        if parallel:
            print(f"Mode: Parallel (scanning {len(ports)} ports simultaneously)")
            print(f"Estimated time: {total_attempts * timeout / (60 * len(ports)):.1f} minutes")
        else:
            print(f"Mode: Sequential")
            print(f"Estimated time: {total_attempts * timeout / 60:.1f} minutes")
        print(f"{'='*70}\n")

        if parallel:
            self._scan_parallel(ports, baud_rates, start_addr, end_addr, timeout, total_attempts)
        else:
            self._scan_sequential(ports, baud_rates, start_addr, end_addr, timeout, total_attempts)

        print(f"\n\n{'='*70}")
        print(f"Scan Complete")
        print(f"{'='*70}")
        self._print_summary()

    def _scan_parallel(self, ports, baud_rates, start_addr, end_addr, timeout, total_attempts):
        """Scan multiple ports in parallel using ThreadPoolExecutor."""
        completed_attempts = [0]  # Use list to allow mutation in nested function

        def update_progress():
            with self.progress_lock:
                completed_attempts[0] += 1
                if completed_attempts[0] % 50 == 0 or completed_attempts[0] == total_attempts:
                    progress = (completed_attempts[0] / total_attempts) * 100
                    print(f"  Overall progress: {progress:.1f}% ({completed_attempts[0]}/{total_attempts})", end='\r')

        # Create a thread pool with one thread per port
        with ThreadPoolExecutor(max_workers=len(ports)) as executor:
            futures = []

            # Submit scanning tasks for each port
            for port in ports:
                future = executor.submit(
                    self._scan_port,
                    port,
                    baud_rates,
                    start_addr,
                    end_addr,
                    timeout,
                    update_progress
                )
                futures.append((port, future))

            # Wait for all port scans to complete
            for port, future in futures:
                try:
                    devices_found = future.result()
                    print(f"\n  ✓ Port {port}: Found {devices_found} device(s)                    ")
                except Exception as e:
                    print(f"\n  ✗ Port {port}: Error - {e}")

    def _scan_sequential(self, ports, baud_rates, start_addr, end_addr, timeout, total_attempts):
        """Scan ports sequentially (original behavior)."""
        attempt = 0

        for port in ports:
            full_port = f'/dev/{port}'
            print(f"\n{'─'*70}")
            print(f"Scanning port: {port}")
            print(f"{'─'*70}")

            for baud_rate in baud_rates:
                print(f"\n  Baud rate: {baud_rate}")
                devices_at_baud = 0

                for address in range(start_addr, end_addr + 1):
                    attempt += 1
                    if attempt % 50 == 0:
                        progress = (attempt / total_attempts) * 100
                        print(f"    Progress: {progress:.1f}% ({attempt}/{total_attempts})", end='\r')

                    # Try to identify device type
                    device_info = self._probe_device(full_port, address, baud_rate, timeout)

                    if device_info:
                        devices_at_baud += 1
                        with self.devices_lock:
                            self.found_devices.append(device_info)
                        print(f"\n    ✓ Found: {device_info['type']:12} at 0x{address:02X} - {device_info['description']}")

                if devices_at_baud == 0:
                    print(f"    No devices found at {baud_rate} baud")

    def _scan_port(self, port, baud_rates, start_addr, end_addr, timeout, progress_callback):
        """
        Scan a single port across all baud rates and addresses.

        This function is called in parallel for each port.
        """
        full_port = f'/dev/{port}'
        devices_found = 0

        for baud_rate in baud_rates:
            for address in range(start_addr, end_addr + 1):
                # Update progress
                if progress_callback:
                    progress_callback()

                # Try to identify device type
                device_info = self._probe_device(full_port, address, baud_rate, timeout)

                if device_info:
                    devices_found += 1
                    with self.devices_lock:
                        self.found_devices.append(device_info)

                    # Print discovery immediately (thread-safe)
                    with self.progress_lock:
                        print(f"\n  ✓ {port}: Found {device_info['type']:12} at 0x{address:02X} ({baud_rate} baud) - {device_info['description']}")

        return devices_found

    def _probe_device(
        self,
        port: str,
        address: int,
        baud_rate: int,
        timeout: float
    ) -> Optional[Dict]:
        """
        Probe a specific address to identify device type.

        Returns:
            Dict with device info if found, None otherwise
        """
        # Optimize: Try device types in order of likelihood based on baud rate
        # This reduces unnecessary timeouts
        device_types_to_try = []

        # Relays are almost always at 38400
        if baud_rate == 38400:
            device_types_to_try = ['Relay', 'pH', 'EC', 'DO', 'Water_Level']
        # Sensors are almost always at 9600 or 4800
        else:
            device_types_to_try = ['pH', 'EC', 'DO', 'Water_Level', 'Relay']

        # Try each device type pattern in optimized order
        for device_type in device_types_to_try:
            pattern = self.DEVICE_PATTERNS[device_type]
            baud_match = baud_rate in pattern['typical_bauds']

            # Skip unlikely combinations to save time
            # Don't try sensors at 38400 baud unless typical
            if baud_rate == 38400 and device_type != 'Relay':
                continue
            # Don't try relays at 4800/9600 baud
            if baud_rate in [4800, 9600] and device_type == 'Relay':
                continue

            try:
                # Read holding registers
                response = self.modbus_client.read_holding_registers(
                    port=port,
                    address=pattern['register'],
                    count=pattern['count'],
                    slave_addr=address,
                    baudrate=baud_rate,
                    timeout=timeout,
                    device_name=f'scanner_{device_type}'
                )

                # Check if response is valid
                if not response.isError() and response.registers:
                    # For EC sensor, parse as floats
                    if device_type == 'EC' and len(response.registers) >= 2:
                        values = self._parse_ec_response(response.registers)
                    # For pH sensor
                    elif device_type == 'pH' and len(response.registers) >= 2:
                        values = response.registers[:2]
                    # For DO sensor
                    elif device_type == 'DO' and len(response.registers) >= 2:
                        values = response.registers[:2]
                    # For Water Level sensor
                    elif device_type == 'Water_Level' and len(response.registers) >= 1:
                        # Handle signed 16-bit value
                        val = response.registers[0]
                        if val > 32767:
                            val -= 65536
                        values = [val]
                    # For Relay
                    elif device_type == 'Relay':
                        values = response.registers[:1]
                    else:
                        continue

                    # Check if values are reasonable for this device type
                    try:
                        if pattern['value_check'](values):
                            # Found a match! Return immediately, don't try other device types
                            return {
                                'type': device_type,
                                'port': port,
                                'address': address,
                                'baud_rate': baud_rate,
                                'register': pattern['register'],
                                'values': values,
                                'description': pattern['value_format'](values),
                                'baud_match': baud_match
                            }
                    except Exception as e:
                        # Value check failed, not this device type
                        continue

            except Exception as e:
                # Connection failed, try next device type
                # Note: This is expected for most addresses (no device present)
                continue

        return None

    def _parse_ec_response(self, registers: List[int]) -> List[float]:
        """Parse EC sensor response as float values."""
        try:
            # EC sensor returns floats in a specific byte order
            # Convert pairs of registers to float
            if len(registers) >= 2:
                # Combine registers into bytes
                byte_data = bytearray()
                for reg in registers[:2]:
                    byte_data.extend([(reg >> 8) & 0xFF, reg & 0xFF])

                # Reorder bytes for EC value (based on ec.py implementation)
                ec_bytes = bytearray([byte_data[2], byte_data[3], byte_data[0], byte_data[1]])
                ec_value = struct.unpack('>f', ec_bytes)[0]
                return [ec_value]
        except Exception as e:
            pass

        return [0.0]

    def _print_summary(self):
        """Print a summary of found devices."""
        if not self.found_devices:
            print("\nNo devices found.")
            return

        print(f"\nFound {len(self.found_devices)} device(s):\n")

        # Group by device type
        by_type = {}
        for device in self.found_devices:
            device_type = device['type']
            if device_type not in by_type:
                by_type[device_type] = []
            by_type[device_type].append(device)

        for device_type, devices in sorted(by_type.items()):
            print(f"\n{device_type} Sensors ({len(devices)}):")
            print(f"{'─'*70}")
            for device in devices:
                baud_indicator = "✓" if device['baud_match'] else "?"
                print(f"  [{baud_indicator}] {device['port']:15} | "
                      f"Addr: 0x{device['address']:02X} ({device['address']:3d}) | "
                      f"Baud: {device['baud_rate']:6d} | "
                      f"{device['description']}")

        print(f"\n{'='*70}")
        print("Configuration snippets for device.conf:")
        print(f"{'='*70}\n")

        for device_type, devices in sorted(by_type.items()):
            print(f"\n[SENSORS] # {device_type}")
            for i, device in enumerate(devices):
                sensor_name = f"{device_type}_main" if i == 0 else f"{device_type}_{i+1}"
                port_name = device['port'].replace('/dev/', '')
                print(f"{sensor_name} = {device_type}, main, {port_name}, "
                      f"{device['baud_rate']}, 0x{device['address']:02X}")

        print("\n")


def main():
    """Main entry point for the scanner."""
    parser = argparse.ArgumentParser(description='Modbus Device Scanner')
    parser.add_argument('--ports', type=str, default='ttyAMA1,ttyAMA2,ttyAMA3,ttyAMA4',
                       help='Comma-separated list of ports to scan (default: ttyAMA1,ttyAMA2,ttyAMA3,ttyAMA4)')
    parser.add_argument('--bauds', type=str, default='4800,9600,38400',
                       help='Comma-separated list of baud rates (default: 4800,9600,38400)')
    parser.add_argument('--start-addr', type=str, default='0x01',
                       help='Start address in hex (default: 0x01)')
    parser.add_argument('--end-addr', type=str, default='0x50',
                       help='End address in hex (default: 0x50 for quick scan, use 0xFF for full scan)')
    parser.add_argument('--timeout', type=float, default=0.3,
                       help='Timeout per probe in seconds (default: 0.3)')
    parser.add_argument('--full', action='store_true',
                       help='Full scan (addresses 0x01-0xFF). Default is quick scan (0x01-0x50)')
    parser.add_argument('--sequential', action='store_true',
                       help='Scan ports sequentially instead of in parallel')

    args = parser.parse_args()

    # Parse arguments
    ports = [p.strip() for p in args.ports.split(',')]
    baud_rates = [int(b.strip()) for b in args.bauds.split(',')]
    start_addr = int(args.start_addr, 16)
    end_addr = int(args.end_addr, 16)

    # Full scan mode (default is quick scan)
    if args.full:
        print("Full scan mode enabled (0x01-0xFF)")
        end_addr = 0xFF
    else:
        print("Quick scan mode (default). Use --full for addresses 0x01-0xFF")
        end_addr = min(end_addr, 0x50)

    # Create scanner and run
    scanner = ModbusScanner()
    scanner.scan(
        ports=ports,
        baud_rates=baud_rates,
        address_range=(start_addr, end_addr),
        timeout=args.timeout,
        parallel=not args.sequential
    )


if __name__ == '__main__':
    main()
