"""Human-in-the-loop gate: wait for responses in human_inbox/."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def list_pending_questions() -> list[dict]:
    """Return unanswered questions from human_outbox."""
    outbox = settings.human_outbox
    if not outbox.exists():
        return []
    questions = []
    for f in sorted(outbox.glob("question_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["file"] = str(f.name)
            questions.append(data)
        except json.JSONDecodeError:
            continue
    return questions


def check_for_human_response(since: datetime | None = None) -> str | None:
    """Check human_inbox for a new .txt response."""
    inbox = settings.human_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    responses = sorted(inbox.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for resp in responses:
        mtime = datetime.fromtimestamp(resp.stat().st_mtime, tz=timezone.utc)
        if since and mtime <= since:
            continue
        content = resp.read_text(encoding="utf-8").strip()
        if content:
            logger.info("Human response received: %s", resp.name)
            # Archive processed response
            archive = inbox / "processed"
            archive.mkdir(exist_ok=True)
            resp.rename(archive / resp.name)
            return content
    return None


def wait_for_human(
    question: str,
    *,
    timeout_seconds: int = 3600,
    poll_interval: int = 10,
) -> str | None:
    """Block until human responds or timeout."""
    start = datetime.now(timezone.utc)
    logger.info("Waiting for human input (timeout=%ds): %s", timeout_seconds, question[:100])

    while (datetime.now(timezone.utc) - start).total_seconds() < timeout_seconds:
        response = check_for_human_response(since=start)
        if response:
            return response
        time.sleep(poll_interval)

    logger.warning("Human input timeout after %ds", timeout_seconds)
    return None


def submit_human_response(text: str, filename: str = "") -> Path:
    """Helper to write a human response (used by CLI/dashboard)."""
    inbox = settings.human_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = filename or f"response_{ts}.txt"
    path = inbox / name
    path.write_text(text, encoding="utf-8")
    return path