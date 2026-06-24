"""Unit tests for tool sandbox policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from policy import (
    is_docker_command_blocked,
    is_git_command_blocked,
    is_shell_command_blocked,
    resolve_safe_path,
)


class TestPathPolicy:
    def test_relative_path_resolves_in_workspace(self, tmp_path):
        (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
        p = resolve_safe_path("hello.txt", workspace=tmp_path, allowed_roots=[tmp_path], must_exist=True)
        assert p == tmp_path / "hello.txt"

    def test_path_outside_workspace_raises(self, tmp_path):
        with pytest.raises(PermissionError, match="outside allowed"):
            resolve_safe_path("/etc/passwd", workspace=tmp_path, allowed_roots=[tmp_path])


class TestShellPolicy:
    def test_blocks_dangerous_commands(self):
        assert is_shell_command_blocked("rm -rf /") is True

    def test_allows_safe_commands(self):
        assert is_shell_command_blocked("echo hello") is False


class TestGitPolicy:
    def test_blocks_force_push(self):
        assert is_git_command_blocked("push --force origin main") is True

    def test_allows_status(self):
        assert is_git_command_blocked("status") is False


class TestDockerPolicy:
    def test_blocks_system_prune(self):
        assert is_docker_command_blocked("system prune -a") is True

    def test_allows_ps(self):
        assert is_docker_command_blocked("ps") is False