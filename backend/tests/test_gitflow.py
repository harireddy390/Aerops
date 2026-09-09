"""Phase-2 tests: git isolation, harness tiers, reflexion, delivery merge."""
import asyncio
import subprocess
from pathlib import Path

import pytest

import tests.conftest  # noqa: F401
from app.diagnosis.code_diagnosis_agent import CodeFixProposal
from app.diagnosis.reflexion_agent import propose_with_reflexion
from app.remediation import git_workspace
from app.remediation.test_harness import phase_regression, phase_syntax, verify


def _repo(tmp_path: Path, files: dict | None = None) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    for name, content in (files or {"w.js": "const a = 1;\n"}).items():
        (tmp_path / name).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_workspace_branch_commit_merge(tmp_path):
    repo = _repo(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    async def go():
        ws = await git_workspace.open_workspace(repo, 1, "abc123")
        assert ws.branch == "aeroops/fix-1-abc123" and ws.base_ref == head
        (repo / "w.js").write_text("const a = 2;\n")
        ok, stat = await git_workspace.commit_fix(
            ws, incident_id=1, fingerprint="abc123", root_cause="x", model="m")
        assert ok and "w.js" in stat
        ok, msg = await git_workspace.merge_fast_forward(ws, "main")
        assert ok, msg
        return (repo / "w.js").read_text()
    assert asyncio.run(go()) == "const a = 2;\n"


def test_workspace_abandon_restores(tmp_path):
    repo = _repo(tmp_path)

    async def go():
        ws = await git_workspace.open_workspace(repo, 2, "zz")
        (repo / "w.js").write_text("BROKEN(((")
        assert await git_workspace.abandon(ws) == "abandoned"
        code, branches = await git_workspace._git(repo, "branch", "--list", "aeroops/*")
        return (repo / "w.js").read_text(), branches.strip()
    content, leftover = asyncio.run(go())
    assert content == "const a = 1;\n" and leftover == ""


def test_workspace_refuses_dirty(tmp_path):
    repo = _repo(tmp_path)
    (repo / "w.js").write_text("dirty")
    with pytest.raises(RuntimeError, match="dirty"):
        asyncio.run(git_workspace.open_workspace(repo, 3, "zz"))


def test_harness_syntax_and_scoped_tests(tmp_path):
    good = tmp_path / "ok.py"
    good.write_text("x = 1\n")
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n")
    (tmp_path / "test_ok.py").write_text("def test_x():\n    assert 1 == 1\n")
    assert asyncio.run(phase_syntax(good)).ok is True
    assert asyncio.run(phase_syntax(bad)).ok is False
    assert asyncio.run(phase_regression(good)).ok is True
    assert asyncio.run(verify(bad)).ok is False


def test_reflexion_retries_then_verifies():
    calls = []

    async def propose_fn():
        calls.append(1)
        return (CodeFixProposal(root_cause="r", search_block="a",
                                replacement_block="b",
                                verification_command="node --check"), "mock")

    async def try_patch(p):
        return True, ""

    p, provider, outcome = asyncio.run(
        propose_with_reflexion(propose_fn, error="boom", context_block="a",
                               try_patch=try_patch))
    assert outcome == "verified" and provider == "mock" and len(calls) == 1
    # now force repeated failures -> escalated after bounded retries.
    # mock the model so refinement always yields a fresh valid proposal.
    import app.diagnosis.code_diagnosis_agent as agent_mod

    async def fake_ollama(prompt):
        return ('{"root_cause": "r2", "search_block": "a", '
                '"replacement_block": "b", "verification_command": "node --check"}')

    import unittest.mock as mock
    tries = []

    async def always_fail(p):
        tries.append(1)
        return False, "nope"

    with mock.patch.object(agent_mod, "_ask_openai", return_value=None), \
         mock.patch.object(agent_mod, "_ask_ollama", side_effect=fake_ollama):
        p2, _, outcome2 = asyncio.run(
            propose_with_reflexion(propose_fn, error="boom", context_block="a",
                                   try_patch=always_fail))
    assert outcome2 == "escalated" and len(tries) == 3  # initial + 2 reflexions


def test_draft_pr_pending_without_remote():
    import asyncio
    from app.db.database import SessionLocal, init_db
    from app.db.models import Service
    from app.engines import incident_engine
    from app.remediation import delivery_gate, git_workspace
    init_db()
    db = SessionLocal()
    try:
        svc = Service(name="pr-test", command="x", working_directory=".")
        db.add(svc)
        db.commit()
        inc = incident_engine.create_incident(db, service_id=svc.id, type="frontend",
                                              severity="critical", error_message="boom")
        db.commit()

        async def go():
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                repo = Path(td)
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
                (repo / "f.js").write_text("a\n")
                subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True)
                ws = await git_workspace.open_workspace(repo, inc.id, "abc")
                (repo / "f.js").write_text("b\n")
                ok, _ = await git_workspace.commit_fix(
                    ws, incident_id=inc.id, fingerprint="abc",
                    root_cause="r", model="m")
                assert ok
                body = await delivery_gate.deliver_draft_pr(
                    db, ws, incident=inc, root_cause="r",
                    stack="boom", test_results="green", diff_stat="f.js | 1 +-")
                return body
        body = asyncio.run(go())
        assert "Root cause" in body and "Verification" in body and "Diff" in body
        db.commit()
    finally:
        db.close()


def test_deploy_restart_replaces_process():
    """Deploy must stop-then-start: the old process has to die for the merge
    to take effect (idempotent start would silently keep old code)."""
    import time
    from app.engines import restart_manager
    pid1 = restart_manager.start(99981, "python -m http.server 4190", ".", {})
    assert pid1 > 0
    restart_manager.stop(99981)
    time.sleep(1)
    assert restart_manager.exit_code(99981) is not None
    pid2 = restart_manager.start(99981, "python -m http.server 4190", ".", {})
    assert pid2 != pid1
    restart_manager.stop(99981)
