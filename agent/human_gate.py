"""Human-in-the-loop gate: non-blocking park/resume via Redis + inbox files."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from task_watcher import Task, enqueue_task_front, list_awaiting_human, unpark_awaiting_human

logger = logging.getLogger(__name__)


def new_question_id() -> str:
    return uuid.uuid4().hex[:12]


def list_pending_questions() -> list[dict]:
    """Return unanswered questions from human_outbox and Redis park."""
    outbox = settings.human_outbox
    questions: list[dict] = []
    if outbox.exists():
        for f in sorted(outbox.glob("question_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["file"] = str(f.name)
                questions.append(data)
            except json.JSONDecodeError:
                continue
    for parked in list_awaiting_human():
        questions.append(
            {
                "question_id": parked.get("question_id", ""),
                "question": parked.get("question", ""),
                "goal_id": parked.get("goal_id", ""),
                "source": "redis_parked",
            }
        )
    return questions


def write_question(question: str, context: str = "", question_id: str = "") -> Path:
    """Write a correlated question file to human_outbox."""
    inbox = settings.human_outbox
    inbox.mkdir(parents=True, exist_ok=True)
    qid = question_id or new_question_id()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    payload = {
        "question_id": qid,
        "question": question,
        "context": context,
        "timestamp": ts,
    }
    out_path = inbox / f"question_{qid}_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def check_for_human_response(question_id: str = "") -> str | None:
    """Check human_inbox for a response, optionally correlated by question_id prefix."""
    inbox = settings.human_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    responses = sorted(inbox.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for resp in responses:
        content = resp.read_text(encoding="utf-8").strip()
        if not content:
            continue
        # Match response_{question_id}.txt or any response if no id specified
        if question_id and question_id not in resp.name:
            continue
        logger.info("Human response received: %s", resp.name)
        archive = inbox / "processed"
        archive.mkdir(exist_ok=True)
        resp.rename(archive / resp.name)
        return content
    return None


def process_awaiting_responses() -> int:
    """Resume parked goals when matching human responses arrive. Returns count resumed."""
    resumed = 0
    for parked in list_awaiting_human():
        qid = parked.get("question_id", "")
        response = check_for_human_response(question_id=qid) if qid else check_for_human_response()
        if not response:
            continue
        goal_id = parked["goal_id"]
        unpark_awaiting_human(goal_id)
        task = Task.from_dict(parked)
        task.goal = f"{task.goal}\n\nHuman guidance ({qid}): {response}"
        enqueue_task_front(task)
        logger.info("Resumed parked goal %s after human response", goal_id)
        resumed += 1
    return resumed


def submit_human_response(text: str, question_id: str = "") -> Path:
    """Write a human response correlated to a question_id."""
    inbox = settings.human_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"response_{question_id}_{ts}.txt" if question_id else f"response_{ts}.txt"
    path = inbox / name
    path.write_text(text, encoding="utf-8")
    return path