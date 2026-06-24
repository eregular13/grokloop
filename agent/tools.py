"""Sandboxed tool implementations for LocalGrokLoop."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from config import settings
from memory import memory_store

logger = logging.getLogger(__name__)

# Paths the agent may write to
_WRITABLE_ROOTS = [
    settings.workspace_path.resolve(),
]
if settings.self_edit_mode:
    _WRITABLE_ROOTS.append(settings.project_path.resolve())


def _resolve_safe(path: str, *, must_exist: bool = False) -> Path:
    """Resolve path and ensure it stays within allowed roots."""
    p = Path(path)
    if not p.is_absolute():
        p = (settings.workspace_path / p).resolve()
    else:
        p = p.resolve()

    allowed_roots = [settings.workspace_path.resolve()]
    if settings.self_edit_mode:
        allowed_roots.append(settings.project_path.resolve())
        allowed_roots.append(settings.data_path.resolve())

    if not any(str(p).startswith(str(root)) for root in allowed_roots):
        raise PermissionError(f"Path outside allowed workspace: {p}")

    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")
    return p


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} chars omitted]"


# ── Tool implementations ───────────────────────────────────────────


def read_file(path: str, offset: int = 0, limit: int = 500) -> str:
    """Read a file from the workspace (with optional line offset/limit)."""
    p = _resolve_safe(path, must_exist=True)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    selected = lines[offset : offset + limit]
    header = f"File: {p} ({len(lines)} lines total)\n"
    body = "\n".join(f"{offset + i + 1}|{line}" for i, line in enumerate(selected))
    return _truncate(header + body)


def write_file(path: str, content: str, append: bool = False) -> str:
    """Write or append content to a file in the workspace."""
    p = _resolve_safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(p, mode, encoding="utf-8") as f:
        f.write(content)
    action = "Appended to" if append else "Wrote"
    return f"{action} {p} ({len(content)} chars)"


def list_directory(path: str = ".", pattern: str = "*") -> str:
    """List files in a workspace directory."""
    p = _resolve_safe(path, must_exist=True)
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {p}")
    entries = sorted(p.glob(pattern))
    lines = [f"{'[DIR] ' if e.is_dir() else '[FILE]'} {e.name}" for e in entries[:200]]
    return f"Directory: {p}\n" + "\n".join(lines) or "(empty)"


def run_shell(command: str, cwd: str = "", timeout: int | None = None) -> str:
    """Run a shell command. Scoped to workspace by default."""
    work_dir = _resolve_safe(cwd or str(settings.workspace_path))
    if not work_dir.is_dir():
        work_dir = settings.workspace_path

    timeout = timeout or settings.tool_timeout_seconds
    dangerous = ["rm -rf /", "mkfs", ":(){", "dd if=", "> /dev/sd"]
    if any(d in command for d in dangerous):
        return "BLOCKED: Command matches dangerous pattern."

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        output = f"exit_code={result.returncode}\n"
        if result.stdout:
            output += f"stdout:\n{result.stdout}\n"
        if result.stderr:
            output += f"stderr:\n{result.stderr}\n"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as exc:
        return f"ERROR: {exc}"


def run_python(code: str, timeout: int | None = None) -> str:
    """Execute Python code in a subprocess with workspace on sys.path."""
    timeout = timeout or settings.tool_timeout_seconds
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir=settings.workspace_path
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            cwd=settings.workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(settings.workspace_path)},
        )
        output = f"exit_code={result.returncode}\n"
        if result.stdout:
            output += f"stdout:\n{result.stdout}\n"
        if result.stderr:
            output += f"stderr:\n{result.stderr}\n"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def git_command(args: str) -> str:
    """Run a git command in the workspace. Destructive ops blocked."""
    blocked = ["push --force", "reset --hard", "clean -fdx", "branch -D"]
    if any(b in args for b in blocked):
        return "BLOCKED: Destructive git operation requires human approval."
    return run_shell(f"git {args}", cwd=str(settings.workspace_path))


def docker_command(args: str) -> str:
    """Run docker CLI. Requires mounted docker.sock."""
    blocked = ["rm -f $(docker ps", "system prune -a", "volume rm"]
    if any(b in args for b in blocked):
        return "BLOCKED: Destructive docker operation."
    return run_shell(f"docker {args}", timeout=180)


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web via local SearXNG instance."""
    url = f"{settings.searxng_url.rstrip('/')}/search"
    params = {"q": query, "format": "json", "categories": "general"}
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"Search failed: {exc}. Is SearXNG running?"

    results = data.get("results", [])[:max_results]
    if not results:
        return f"No results for: {query}"

    lines = [f"Search: {query}"]
    for r in results:
        lines.append(f"- {r.get('title', 'N/A')}\n  {r.get('url', '')}\n  {r.get('content', '')[:200]}")
    return _truncate("\n".join(lines))


def store_memory(content: str, memory_type: str = "observation", tags: str = "") -> str:
    """Store information in persistent vector memory."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    doc_id = memory_store.store(content, memory_type=memory_type, tags=tag_list)
    return f"Stored memory {doc_id} ({memory_type})"


def search_memory(query: str, top_k: int = 5) -> str:
    """Search persistent vector memory."""
    hits = memory_store.search(query, top_k=top_k)
    if not hits:
        return "No memories found."
    lines = [f"Memory search: {query}"]
    for h in hits:
        lines.append(f"- [{h['metadata'].get('type', '?')}] {h['content'][:500]}")
    return "\n".join(lines)


def ask_human(question: str, context: str = "") -> str:
    """Queue a question for human review. Loop pauses until response arrives."""
    inbox = settings.human_outbox
    inbox.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    payload = {"question": question, "context": context, "timestamp": ts}
    out_path = inbox / f"question_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return (
        f"Question queued at {out_path}. "
        "Human should drop a .txt response in human_inbox/ with matching timestamp or latest file."
    )


# ── LangChain tool registry ────────────────────────────────────────


class ReadFileInput(BaseModel):
    path: str = Field(description="File path relative to workspace or absolute within allowed roots")
    offset: int = Field(default=0, description="Line offset to start reading")
    limit: int = Field(default=500, description="Max lines to read")


class WriteFileInput(BaseModel):
    path: str
    content: str
    append: bool = False


class ListDirInput(BaseModel):
    path: str = "."
    pattern: str = "*"


class ShellInput(BaseModel):
    command: str
    cwd: str = ""
    timeout: int | None = None


class PythonInput(BaseModel):
    code: str
    timeout: int | None = None


class GitInput(BaseModel):
    args: str = Field(description="Git arguments, e.g. 'status' or 'log --oneline -5'")


class DockerInput(BaseModel):
    args: str


class WebSearchInput(BaseModel):
    query: str
    max_results: int = 5


class MemoryStoreInput(BaseModel):
    content: str
    memory_type: str = "observation"
    tags: str = ""


class MemorySearchInput(BaseModel):
    query: str
    top_k: int = 5


class AskHumanInput(BaseModel):
    question: str
    context: str = ""


def get_tools() -> list[StructuredTool]:
    """Return all agent tools as LangChain StructuredTools."""
    return [
        StructuredTool.from_function(read_file, name="read_file", args_schema=ReadFileInput),
        StructuredTool.from_function(write_file, name="write_file", args_schema=WriteFileInput),
        StructuredTool.from_function(list_directory, name="list_directory", args_schema=ListDirInput),
        StructuredTool.from_function(run_shell, name="run_shell", args_schema=ShellInput),
        StructuredTool.from_function(run_python, name="run_python", args_schema=PythonInput),
        StructuredTool.from_function(git_command, name="git_command", args_schema=GitInput),
        StructuredTool.from_function(docker_command, name="docker_command", args_schema=DockerInput),
        StructuredTool.from_function(web_search, name="web_search", args_schema=WebSearchInput),
        StructuredTool.from_function(store_memory, name="store_memory", args_schema=MemoryStoreInput),
        StructuredTool.from_function(search_memory, name="search_memory", args_schema=MemorySearchInput),
        StructuredTool.from_function(ask_human, name="ask_human", args_schema=AskHumanInput),
    ]


def tools_by_name() -> dict[str, Any]:
    return {t.name: t for t in get_tools()}