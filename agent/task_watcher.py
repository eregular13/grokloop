"""Task intake: watch /tasks for .txt goal files and Redis queue."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import redis
from task_payload import build_task_payload, goal_content_hash
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import settings

logger = logging.getLogger(__name__)

TASK_QUEUE_KEY = "localgrokloop:task_queue"
TASK_ACTIVE_KEY = "localgrokloop:active_goal"
TASK_HISTORY_KEY = "localgrokloop:task_history"
AWAITING_HUMAN_KEY = "localgrokloop:awaiting_human"


class Task:
    def __init__(
        self,
        goal_id: str,
        goal: str,
        source: str = "file",
        *,
        goal_hash: str = "",
        thread_id: str = "",
        question_id: str = "",
    ):
        self.goal_id = goal_id
        self.goal = goal
        self.source = source
        self.goal_hash = goal_hash or goal_content_hash(goal)
        self.thread_id = thread_id or f"goal_{goal_id}"
        self.question_id = question_id
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "goal": self.goal,
            "source": self.source,
            "goal_hash": self.goal_hash,
            "thread_id": self.thread_id,
            "question_id": self.question_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        t = cls(
            data["goal_id"],
            data["goal"],
            data.get("source", "queue"),
            goal_hash=data.get("goal_hash", ""),
            thread_id=data.get("thread_id", ""),
            question_id=data.get("question_id", ""),
        )
        t.created_at = data.get("created_at", t.created_at)
        return t


def get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def queue_length() -> int:
    return get_redis().llen(TASK_QUEUE_KEY)


def enqueue_task(goal: str, source: str = "cli", *, goal_id: str = "") -> Task:
    """Add a goal to the Redis task queue with a unique ID."""
    r = get_redis()
    payload = build_task_payload(goal, source, goal_id=goal_id)
    task = Task.from_dict(payload)
    r.rpush(TASK_QUEUE_KEY, json.dumps(task.to_dict()))
    r.lpush(TASK_HISTORY_KEY, json.dumps({**task.to_dict(), "status": "queued"}))
    r.ltrim(TASK_HISTORY_KEY, 0, 99)
    logger.info("Enqueued task %s from %s", task.goal_id, source)
    return task


def enqueue_task_front(task: Task) -> None:
    """Re-queue a task at the front (for human resume)."""
    r = get_redis()
    r.lpush(TASK_QUEUE_KEY, json.dumps(task.to_dict()))


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


def park_awaiting_human(task: Task, question: str, question_id: str) -> None:
    """Park a goal awaiting human input without blocking the worker."""
    r = get_redis()
    payload = {
        **task.to_dict(),
        "question": question,
        "question_id": question_id,
        "parked_at": datetime.now(timezone.utc).isoformat(),
    }
    r.hset(AWAITING_HUMAN_KEY, task.goal_id, json.dumps(payload))
    r.lpush(
        TASK_HISTORY_KEY,
        json.dumps({**task.to_dict(), "status": "awaiting_human", "question_id": question_id}),
    )
    logger.info("Parked goal %s awaiting human (question_id=%s)", task.goal_id, question_id)


def list_awaiting_human() -> list[dict]:
    r = get_redis()
    items = r.hgetall(AWAITING_HUMAN_KEY)
    return [json.loads(v) for v in items.values()]


def unpark_awaiting_human(goal_id: str) -> dict | None:
    r = get_redis()
    data = r.hget(AWAITING_HUMAN_KEY, goal_id)
    if data:
        r.hdel(AWAITING_HUMAN_KEY, goal_id)
        return json.loads(data)
    return None


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
            time.sleep(0.3)
            try:
                ingest_file(path)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", path, exc)


def start_task_watcher() -> Observer:
    settings.tasks_path.mkdir(parents=True, exist_ok=True)
    handler = TaskFileHandler()
    observer = Observer()
    observer.schedule(handler, str(settings.tasks_path), recursive=False)
    observer.start()
    logger.info("Task watcher started on %s", settings.tasks_path)
    return observer


def scan_pending_files() -> list[Task]:
    tasks = []
    for f in settings.tasks_path.glob("*.txt"):
        task = ingest_file(f)
        if task:
            tasks.append(task)
    return tasks
