#!/usr/bin/env python3
"""
Modbus Device Scanner Wrapper

Checks prerequisites and launches the modbus scanner.
"""

import sys
import os
import subprocess
import urllib.request

# Ensure we're running from the project root
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

def check_lumina_server():
    """Check if lumina-modbus-server is running."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:8888', timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

def main():
    print("Modbus Device Scanner")
    print("=" * 70)
    print()

    # Check if lumina-modbus-server is running
    if not check_lumina_server():
        print("❌ ERROR: lumina-modbus-server is not running!")
        print()
        print("Please start it first:")
        print("  cd ~/lumina-modbus-server && ./start_server.sh")
        print()
        sys.exit(1)

    print("✓ lumina-modbus-server is running")
    print()

    # Run the scanner with all arguments passed to this script
    cmd = [sys.executable, 'src/sensors/modbus_scanner.py'] + sys.argv[1:]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Scanner failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\n\n⚠ Scan interrupted by user")
        sys.exit(130)

if __name__ == '__main__':
    main()
