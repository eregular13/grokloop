"""Unit tests for tool sandbox policy."""

from __future__ import annotations

import pytest
from policy import (
    classify_shell_risk,
    is_docker_tool_enabled,
    is_git_command_blocked,
    is_shell_allowed,
    is_write_allowed,
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

    def test_prefix_attack_blocked(self, tmp_path):
        """/workspace_evil must not match /workspace prefix check."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        evil = tmp_path / "workspace_evil"
        evil.mkdir()
        secret = evil / "secret.txt"
        secret.write_text("nope", encoding="utf-8")
        with pytest.raises(PermissionError):
            resolve_safe_path(str(secret), workspace=workspace, allowed_roots=[workspace], must_exist=True)


class TestShellPolicy:
    def test_blocks_rm_rf_root(self):
        assert classify_shell_risk("rm -rf /") == "blocked"

    def test_low_risk_allowed_in_edit_mode(self):
        ok, _ = is_shell_allowed("echo hello", "edit")
        assert ok is True

    def test_high_risk_blocked_in_edit_mode(self):
        ok, reason = is_shell_allowed("pip install requests", "edit")
        assert ok is False
        assert "edit" in reason

    def test_high_risk_allowed_in_build_mode(self):
        ok, _ = is_shell_allowed("pip install requests", "build")
        assert ok is True

    def test_docker_critical_requires_operator(self):
        ok, _ = is_shell_allowed("docker ps", "build")
        assert ok is False
        ok2, _ = is_shell_allowed("docker ps", "operator")
        assert ok2 is True


class TestGitPolicy:
    def test_observe_blocks_commit(self):
        assert is_git_command_blocked("commit -m x", "observe") is True

    def test_edit_allows_status(self):
        assert is_git_command_blocked("status", "edit") is False


class TestModeGating:
    def test_write_blocked_in_observe(self):
        assert is_write_allowed("observe") is False

    def test_docker_tool_disabled_by_default(self):
        assert is_docker_tool_enabled(False, "operator") is False
        assert is_docker_tool_enabled(True, "edit") is False
        assert is_docker_tool_enabled(True, "operator") is True
