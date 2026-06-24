"""Task intake: watch /tasks for .txt goal files and Redis queue."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import redis
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import settings

logger = logging.getLogger(__name__)

TASK_QUEUE_KEY = "localgrokloop:task_queue"
TASK_ACTIVE_KEY = "localgrokloop:active_goal"
TASK_HISTORY_KEY = "localgrokloop:task_history"


class Task:
    def __init__(self, goal_id: str, goal: str, source: str = "file"):
        self.goal_id = goal_id
        self.goal = goal
        self.source = source
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "goal": self.goal,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        t = cls(data["goal_id"], data["goal"], data.get("source", "queue"))
        t.created_at = data.get("created_at", t.created_at)
        return t


def _goal_id_from_text(goal: str) -> str:
    return hashlib.sha256(goal.encode()).hexdigest()[:12]


def get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_task(goal: str, source: str = "cli") -> Task:
    """Add a goal to the Redis task queue."""
    r = get_redis()
    task = Task(_goal_id_from_text(goal), goal, source)
    r.rpush(TASK_QUEUE_KEY, json.dumps(task.to_dict()))
    r.lpush(TASK_HISTORY_KEY, json.dumps({**task.to_dict(), "status": "queued"}))
    r.ltrim(TASK_HISTORY_KEY, 0, 99)
    logger.info("Enqueued task %s from %s", task.goal_id, source)
    return task


def dequeue_task(block: bool = True, timeout: int = 5) -> Task | None:
    """Pop next task from queue."""
    r = get_redis()
    if block:
        result = r.blpop(TASK_QUEUE_KEY, timeout=timeout)
        if not result:
            return None
        _, payload = result
    else:
        payload = r.lpop(TASK_QUEUE_KEY)
        if not payload:
            return None
    data = json.loads(payload)
    return Task.from_dict(data)


def set_active_goal(task: Task | None) -> None:
    r = get_redis()
    if task:
        r.set(TASK_ACTIVE_KEY, json.dumps(task.to_dict()))
    else:
        r.delete(TASK_ACTIVE_KEY)


def get_active_goal() -> Task | None:
    r = get_redis()
    data = r.get(TASK_ACTIVE_KEY)
    if not data:
        return None
    return Task.from_dict(json.loads(data))


def get_task_history(limit: int = 20) -> list[dict]:
    r = get_redis()
    items = r.lrange(TASK_HISTORY_KEY, 0, limit - 1)
    return [json.loads(i) for i in items]


def ingest_file(path: Path) -> Task | None:
    """Process a dropped .txt task file."""
    if not path.suffix == ".txt" or not path.exists():
        return None
    goal = path.read_text(encoding="utf-8").strip()
    if not goal:
        return None

    processed = settings.tasks_path / "processed"
    processed.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_name = f"{ts}_{path.stem}.txt"
    path.rename(processed / archive_name)

    return enqueue_task(goal, source=f"file:{archive_name}")


class TaskFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".txt" and path.parent == settings.tasks_path:
            time.sleep(0.3)  # allow write to complete
            try:
                ingest_file(path)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", path, exc)


def start_task_watcher() -> Observer:
    """Start filesystem watcher on /tasks."""
    settings.tasks_path.mkdir(parents=True, exist_ok=True)
    handler = TaskFileHandler()
    observer = Observer()
    observer.schedule(handler, str(settings.tasks_path), recursive=False)
    observer.start()
    logger.info("Task watcher started on %s", settings.tasks_path)
    return observer


def scan_pending_files() -> list[Task]:
    """Ingest any existing .txt files in /tasks on startup."""
    tasks = []
    for f in settings.tasks_path.glob("*.txt"):
        task = ingest_file(f)
        if task:
            tasks.append(task)
    return tasks