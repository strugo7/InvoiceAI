"""Process-wide guard against overlapping Gmail scans.

A full scan fans out into many Gmail + Gemini calls. If two scans run at once
(e.g. a double-clicked "Sync" button, or a manual sync coinciding with the
scheduled monthly job) they duplicate all that work and double the API spend.

`scan_lock` is a single asyncio.Lock shared by the manual `/api/sync` endpoint
and the scheduler. Both run on the same event loop, so one lock serialises them.
Callers should treat "already locked" as *busy* (skip / 409), not queue up.
"""

import asyncio

scan_lock = asyncio.Lock()


def scan_in_progress() -> bool:
    """True if a scan currently holds the lock."""
    return scan_lock.locked()
