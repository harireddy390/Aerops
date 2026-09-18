"""Tests for automated Git Workspace Manager."""
from pathlib import Path
import pytest

from app.remediation.workspace_manager import is_remote_url, workspace_dir_for, ensure_workspace
from app.engines.restart_manager import PROJECT_ROOT


def test_is_remote_url():
    assert is_remote_url("https://github.com/user/repo.git") is True
    assert is_remote_url("http://github.com/user/repo") is True
    assert is_remote_url("git@github.com:user/repo.git") is True
    assert is_remote_url("./frontend") is False
    assert is_remote_url("C:\\code\\my-app") is False
    assert is_remote_url("") is False


def test_workspace_dir_for():
    d = workspace_dir_for(9999)
    assert d.name == "svc_9999"
    assert "workspaces" in str(d)
    assert d.parent.exists()


def test_ensure_workspace_local():
    import asyncio

    class DummyService:
        id = 8888
        repo_path_or_url = "./backend"
        working_directory = "."
        target_branch = "main"

    res = asyncio.run(ensure_workspace(DummyService()))
    assert res == PROJECT_ROOT
