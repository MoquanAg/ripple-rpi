#!/usr/bin/env python3
"""
NPK Sensor Scanner (DC-SNPK-S01)

Scans all serial ports and Modbus addresses to find an NPK soil sensor.
Uses direct serial communication — does NOT require lumina-modbus-server.

Usage:
    python3 scan_npk.py                    # Scan all ports, addrs 1-50, 9600 baud
    python3 scan_npk.py --port /dev/ttyAMA1  # Scan specific port only
    python3 scan_npk.py --addr 1-253       # Full address range
    python3 scan_npk.py --baud 2400,4800,9600  # Try multiple baud rates
"""

import argparse
import glob
import struct
import time
import serial


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def modbus_read(ser, addr, reg_start, reg_count):
    """Send a Modbus RTU read holding registers request and return response bytes."""
    cmd = bytearray([addr, 0x03,
                     (reg_start >> 8) & 0xFF, reg_start & 0xFF,
                     (reg_count >> 8) & 0xFF, reg_count & 0xFF])
    crc = crc16(cmd)
    cmd += struct.pack('<H', crc)

    ser.reset_input_buffer()
    ser.write(cmd)
    time.sleep(0.15)
    return ser.read(100)


def parse_npk_response(data):
    """Parse NPK response: addr(1) + func(1) + byte_count(1) + N(2) + P(2) + K(2) + CRC(2)."""
    if len(data) < 11:
        return None
    if data[1] != 0x03 or data[2] != 0x06:
        return None
    # Verify CRC
    payload = data[:9]
    expected_crc = struct.unpack('<H', data[9:11])[0]
    if crc16(payload) != expected_crc:
        return None
    n = int.from_bytes(data[3:5], byteorder='big')
    p = int.from_bytes(data[5:7], byteorder='big')
    k = int.from_bytes(data[7:9], byteorder='big')
    return n, p, k


def find_serial_ports():
    """Find available serial ports on the system."""
    patterns = ['/dev/ttyAMA*', '/dev/ttyUSB*', '/dev/ttyS0']
    ports = []
    for pat in patterns:
        ports.extend(glob.glob(pat))
    return sorted(ports)


def scan(port, addr_range, baudrates, timeout=0.5):
    """Scan a port across addresses and baud rates for NPK sensor."""
    found = []
    for baud in baudrates:
        try:
            ser = serial.Serial(port, baud, timeout=timeout, bytesize=8, parity='N', stopbits=1)
        except Exception as e:
            print(f"  Cannot open {port} at {baud}: {e}")
            return found

        for addr in addr_range:
            resp = modbus_read(ser, addr, 0x001E, 3)
            if resp:
                result = parse_npk_response(resp)
                if result:
                    n, p, k = result
                    found.append((port, baud, addr, n, p, k))
                    print(f"  FOUND at addr {addr} (0x{addr:02x}), {baud} baud: N={n}, P={p}, K={k}")
                    ser.close()
                    return found

        ser.close()
    return found


def main():
    parser = argparse.ArgumentParser(description='Scan for DC-SNPK-S01 NPK soil sensor')
    parser.add_argument('--port', help='Specific serial port (default: scan all)')
    parser.add_argument('--addr', default='1-50', help='Address range, e.g. 1-253 (default: 1-50)')
    parser.add_argument('--baud', default='9600', help='Comma-separated baud rates (default: 9600)')
    args = parser.parse_args()

    # Parse address range
    if '-' in args.addr:
        start, end = args.addr.split('-')
        addr_range = range(int(start), int(end) + 1)
    else:
        addr_range = [int(args.addr)]

    baudrates = [int(b) for b in args.baud.split(',')]
    ports = [args.port] if args.port else find_serial_ports()

    print(f"Scanning for NPK sensor (DC-SNPK-S01)")
    print(f"  Ports: {', '.join(ports)}")
    print(f"  Addresses: {args.addr}")
    print(f"  Baud rates: {', '.join(str(b) for b in baudrates)}")
    print()

    all_found = []
    for port in ports:
        print(f"Scanning {port}...")
        results = scan(port, addr_range, baudrates)
        all_found.extend(results)
        if not results:
            print(f"  No NPK sensor found")
        print()

    if all_found:
        print("=== Summary ===")
        for port, baud, addr, n, p, k in all_found:
            print(f"  {port} addr={addr} (0x{addr:02x}) baud={baud} → N={n} P={p} K={k}")
        print()
        print("Add to device.conf [SENSORS]:")
        port, baud, addr, _, _, _ = all_found[0]
        print(f'  npk_main = npk, main, "NPK Soil Sensor", {port}, {hex(addr)}, {baud}')
    else:
        print("No NPK sensor found on any port.")
        print("Check: power (12-24V), wiring (yellow=A, blue=B), connections.")


if __name__ == '__main__':
    main()
