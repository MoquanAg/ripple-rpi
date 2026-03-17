"""
Audit Event Sync for Ripple — sends unsynced events to Edge's local server.

Ripple doesn't connect directly to the cloud. Instead, it POSTs unsynced
audit events to the Edge device's local server at POST /api/audit/events.
Edge then uploads everything (its own + Ripple's events) to cloud via RabbitMQ.

The Edge IP is captured from incoming heartbeat requests (server.py).

Usage:
    from audit_sync import start_audit_sync
    start_audit_sync()
"""

import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

SYNC_INTERVAL = 300  # 5 minutes
BATCH_SIZE = 100
EDGE_LOCAL_SERVER_PORT = 9090


def _get_edge_url():
    """Get the Edge local server URL from the persisted edge IP file.

    server.py (separate process) writes the Edge IP to data/edge_ip.txt
    whenever a heartbeat arrives. We read it here since we run in main.py's
    process and can't share in-memory state with server.py.
    """
    try:
        ip_file = os.path.join(os.path.dirname(__file__), "data", "edge_ip.txt")
        if os.path.exists(ip_file):
            with open(ip_file) as f:
                edge_ip = f.read().strip()
            if edge_ip:
                return f"http://{edge_ip}:{EDGE_LOCAL_SERVER_PORT}"
    except Exception:
        pass
    return None


def _sync_loop():
    """Background sync loop — runs every SYNC_INTERVAL seconds."""
    # Wait for first heartbeat to capture Edge IP
    time.sleep(60)
    logger.info("Audit sync thread started (interval=%ds)", SYNC_INTERVAL)

    while True:
        try:
            _sync_once()
        except Exception as e:
            logger.warning("Audit sync cycle failed: %s", e)

        time.sleep(SYNC_INTERVAL)


def _sync_once():
    """Run a single sync cycle: query unsynced → POST to Edge → mark synced."""
    from audit_event import audit

    events = audit.get_unsynced(limit=BATCH_SIZE)
    if not events:
        return

    edge_url = _get_edge_url()
    if not edge_url:
        logger.warning("Audit sync: no Edge IP available (data/edge_ip.txt missing or empty), will retry next cycle")
        return

    logger.info("Syncing %d audit events to Edge at %s", len(events), edge_url)

    try:
        response = requests.post(
            f"{edge_url}/api/audit/events",
            json={"events": events},
            timeout=10,
        )

        if response.status_code == 200:
            result = response.json()
            stored = result.get("stored", 0)
            event_ids = [e["id"] for e in events]
            synced = audit.mark_synced(event_ids)
            logger.info("Audit sync complete: %d events sent, %d stored by Edge, %d marked synced",
                        len(events), stored, synced)
        else:
            logger.warning("Audit sync: Edge returned status %d: %s",
                           response.status_code, response.text[:200])

    except requests.exceptions.ConnectionError:
        logger.warning("Audit sync: Edge unreachable at %s, will retry", edge_url)
    except requests.exceptions.Timeout:
        logger.warning("Audit sync: request to Edge timed out")
    except Exception as e:
        logger.warning("Audit sync: failed to send to Edge: %s", e)


def start_audit_sync():
    """Start the background audit sync daemon thread."""
    # Ensure audit loggers can write to log files. main.py's GlobalLogger only
    # configures its own named logger; module-level loggers (audit_sync, audit_event)
    # have no handlers and messages are silently dropped. Attach a handler to root.
    root = logging.getLogger()
    if not root.handlers:
        import glob as _glob
        log_dir = os.path.join(os.path.dirname(__file__), "log")
        os.makedirs(log_dir, exist_ok=True)
        # Find the latest ripple_ log file to share with main logger
        existing = sorted(_glob.glob(os.path.join(log_dir, "ripple_*.log")))
        log_path = existing[-1] if existing else os.path.join(log_dir, "ripple_audit.log")
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(filename)s - %(funcName)s - %(message)s"))
        root.addHandler(fh)

    thread = threading.Thread(target=_sync_loop, name="AuditSyncThread", daemon=True)
    thread.start()
    logger.info("Audit sync thread launched")
    return thread
