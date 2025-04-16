#!/usr/bin/env python3

import os
import sys
import logging
from datetime import datetime
import globals
from globals import logger

def safe_system_reboot():
    """Safely reboot the system after shutting down all components."""
    try:
        logger.info("Initiating system reboot sequence...")
        
        # Log reboot event
        logger.info(f"System reboot initiated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Ensure scheduler is shutdown
        globals.shutdown_scheduler()
        
        # Sync filesystem to disk
        os.system("sync")
        
        # Execute system reboot command
        logger.info("Executing system reboot command...")
        os.system("sudo reboot")
        
    except Exception as e:
        logger.error(f"Error during system reboot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    safe_system_reboot() 