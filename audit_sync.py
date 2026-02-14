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

import json
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

SYNC_INTERVAL = 300  # 5 minutes
BATCH_SIZE = 100
EDGE_LOCAL_SERVER_PORT = 9090


def _get_edge_url():
    """Get the Edge local server URL from the heartbeat-captured IP."""
    try:
        from server import get_edge_ip
        edge_ip = get_edge_ip()
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
        logger.debug("Audit sync: no Edge IP available yet, will retry next cycle")
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
        logger.debug("Audit sync: Edge unreachable at %s, will retry", edge_url)
    except requests.exceptions.Timeout:
        logger.warning("Audit sync: request to Edge timed out")
    except Exception as e:
        logger.warning("Audit sync: failed to send to Edge: %s", e)


def start_audit_sync():
    """Start the background audit sync daemon thread."""
    thread = threading.Thread(target=_sync_loop, name="AuditSyncThread", daemon=True)
    thread.start()
    logger.info("Audit sync thread launched")
    return thread
