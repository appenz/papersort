"""Ingress log for tracking all file processing in ingest mode."""

import os
import tempfile
from datetime import datetime
from typing import Optional

from papersort import PaperSort
from storage import StorageError


def _get_log_path() -> str:
    """Return monthly log path: --IncomingLog/log/YYYY-MM-ingress.log"""
    month = datetime.now().strftime("%Y-%m")
    return f"--IncomingLog/log/{month}-ingress.log"


def _append(entry: str) -> None:
    """Append entry to ingress log using read-append-upload pattern."""
    log_path = _get_log_path()
    
    # Read existing (empty string if doesn't exist)
    try:
        existing = PaperSort.docstore_driver.read_text(log_path)
    except StorageError:
        existing = ""
    
    # Append and upload via temp file
    updated = existing + entry + "\n"
    fd, temp_path = tempfile.mkstemp(suffix='.log', text=True)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(updated)
        PaperSort.docstore_driver.upload(temp_path, log_path)
    finally:
        os.unlink(temp_path)


def _format(status: str, source: str, dest: Optional[str], summary: str, 
            error: Optional[str] = None) -> str:
    """Format a log entry."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{ts}] {status}", f"  Source: {source}"]
    lines.append(f"  Dest:   {dest or '(not filed)'}")
    lines.append(f"  Summary: {summary}")
    if error:
        lines.append(f"  Error: {error}")
    return "\n".join(lines) + "\n"


def log(status: str, source: str, dest: Optional[str], summary: str,
        error: Optional[str] = None) -> None:
    """Log a file processing event. Fails silently with warning on error."""
    if not PaperSort.log or not PaperSort.docstore_driver:
        return
    try:
        _append(_format(status, source, dest, summary, error))
    except Exception as e:
        PaperSort.print_right(f"⚠ Failed to write ingress log: {e}")
