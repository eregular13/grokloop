"""Policy layer — path restrictions, command risk tiers, mode gating."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Literal

AgentMode = Literal["observe", "edit", "build", "operator"]
ShellRisk = Literal["blocked", "low", "high", "critical"]

# Always blocked regardless of mode
BLOCKED_SHELL_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"mkfs\b",
    r":\(\)\{",
    r"dd\s+if=",
    r">\s*/dev/sd",
    r"curl\s+.*\|\s*bash",
    r"wget\s+.*\|\s*sh",
    r"chmod\s+777\s+/",
    r">\s*/etc/",
]

LOW_RISK_SHELL_PREFIXES = (
    "echo ",
    "ls",
    "dir",
    "pwd",
    "cat ",
    "head ",
    "tail ",
    "find ",
    "grep ",
    "rg ",
    "which ",
    "type ",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "python -m pytest",
    "pytest",
    "python -m compileall",
    "ruff check",
    "ruff format --check",
)

HIGH_RISK_SHELL_PREFIXES = (
    "pip install",
    "pip uninstall",
    "npm install",
    "npm ci",
    "yarn install",
    "make ",
    "cmake ",
    "docker build",
    "docker compose build",
    "git add",
    "git commit",
    "git push",
    "git pull",
    "git merge",
    "git checkout",
)

CRITICAL_SHELL_PREFIXES = (
    "docker ",
    "sudo ",
    "su ",
    "mount ",
    "umount ",
    "chown ",
    "chmod ",
    "systemctl ",
    "netstat ",
    "nmap ",
)

DESTRUCTIVE_GIT_PATTERNS = [
    "push --force",
    "reset --hard",
    "clean -fdx",
    "branch -D",
]

DESTRUCTIVE_DOCKER_PATTERNS = [
    "rm -f $(docker ps",
    "system prune -a",
    "volume rm",
]


def _path_is_under(child: Path, parent: Path) -> bool:
    """True if child is inside parent (immune to prefix tricks)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_safe_path(
    path: str,
    *,
    workspace: Path,
    allowed_roots: list[Path],
    must_exist: bool = False,
) -> Path:
    """Resolve path and ensure it stays within allowed roots."""
    p = Path(path)
    if not p.is_absolute():
        p = (workspace / p).resolve()
    else:
        p = p.resolve()

    resolved_roots = [r.resolve() for r in allowed_roots]
    if not any(_path_is_under(p, root) for root in resolved_roots):
        raise PermissionError(f"Path outside allowed workspace: {p}")

    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")
    return p


def classify_shell_risk(command: str) -> ShellRisk:
    """Classify a shell command by risk tier."""
    cmd = command.strip()
    lower = cmd.lower()

    for pattern in BLOCKED_SHELL_PATTERNS:
        if re.search(pattern, lower):
            return "blocked"

    for prefix in CRITICAL_SHELL_PREFIXES:
        if lower.startswith(prefix):
            return "critical"

    for prefix in HIGH_RISK_SHELL_PREFIXES:
        if lower.startswith(prefix):
            return "high"

    for prefix in LOW_RISK_SHELL_PREFIXES:
        if lower.startswith(prefix):
            return "low"

    # Unknown commands treated as high risk
    return "high"


def is_shell_allowed(command: str, agent_mode: AgentMode) -> tuple[bool, str]:
    """Return (allowed, reason). Uses allowlist-by-mode, not denylist-only."""
    risk = classify_shell_risk(command)
    if risk == "blocked":
        return False, "Command matches blocked pattern."

    mode_allowed: dict[AgentMode, set[ShellRisk]] = {
        "observe": {"low"},
        "edit": {"low"},
        "build": {"low", "high"},
        "operator": {"low", "high", "critical"},
    }
    allowed_risks = mode_allowed.get(agent_mode, {"low"})
    if risk not in allowed_risks:
        return False, (
            f"Command risk '{risk}' not allowed in AGENT_MODE={agent_mode}. "
            "Escalate mode or use ask_human."
        )
    return True, "ok"


def is_git_command_blocked(args: str, agent_mode: AgentMode) -> bool:
    if agent_mode == "observe":
        return not args.strip().startswith(("status", "log", "diff", "branch", "show"))
    return any(pattern in args for pattern in DESTRUCTIVE_GIT_PATTERNS)


def is_docker_command_blocked(args: str) -> bool:
    return any(pattern in args for pattern in DESTRUCTIVE_DOCKER_PATTERNS)


def is_docker_tool_enabled(enable_docker_tool: bool, agent_mode: AgentMode) -> bool:
    return enable_docker_tool and agent_mode == "operator"


def is_write_allowed(agent_mode: AgentMode) -> bool:
    return agent_mode in ("edit", "build", "operator")


def is_python_exec_allowed(agent_mode: AgentMode) -> bool:
    return agent_mode in ("edit", "build", "operator")