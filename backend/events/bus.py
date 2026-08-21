import asyncio
import logging
from typing import Dict, Set, Any
from datetime import datetime, timezone

# Setting up a logger specifically for compliance / audit trails
audit_logger = logging.getLogger("medsync.audit")
audit_logger.setLevel(logging.INFO)
# In a real app, this would log to a secure, write-only logging service
if not audit_logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - AUDIT - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    audit_logger.addHandler(handler)


class EventBus:
    def __init__(self):
        # Maps a channel (e.g., token_number or 'queue') to a set of queues.
        self._channels: Dict[str, Set[asyncio.Queue]] = {}

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Subscribe to a specific channel (e.g., 'queue', or 'token_1')."""
        if channel not in self._channels:
            self._channels[channel] = set()
        
        q = asyncio.Queue()
        self._channels[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        """Unsubscribe a queue from a channel."""
        if channel in self._channels:
            self._channels[channel].discard(q)
            if not self._channels[channel]:
                del self._channels[channel]

    async def publish(self, channel: str, message: Any):
        """Publish a message to all subscribers of a channel."""
        if channel in self._channels:
            for q in self._channels[channel]:
                await q.put(message)

    def log_audit_event(self, action: str, details: str, user_role: str):
        """
        Log an audit event for HIPAA/GDPR compliance.
        Must be used whenever PHI/PII is accessed or modified.
        """
        audit_logger.info(f"Role: {user_role} | Action: {action} | Details: {details}")

# Global instance for the application
event_bus = EventBus()
