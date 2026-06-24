"""Policy layer — path restrictions and command blocklists."""

from __future__ import annotations

from pathlib import Path

DANGEROUS_SHELL_PATTERNS = [
    "rm -rf /",
    "mkfs",
    ":(){",
    "dd if=",
    "> /dev/sd",
]

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

    if not any(str(p).startswith(str(root.resolve())) for root in allowed_roots):
        raise PermissionError(f"Path outside allowed workspace: {p}")

    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")
    return p


def is_shell_command_blocked(command: str) -> bool:
    return any(pattern in command for pattern in DANGEROUS_SHELL_PATTERNS)


def is_git_command_blocked(args: str) -> bool:
    return any(pattern in args for pattern in DESTRUCTIVE_GIT_PATTERNS)


def is_docker_command_blocked(args: str) -> bool:
    return any(pattern in args for pattern in DESTRUCTIVE_DOCKER_PATTERNS)