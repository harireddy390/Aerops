"""Phase-3 tests: encrypted tokens, schemas, multifile context, v2 contract,
multi-diff apply, custom harness tier, push safety."""
import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

import tests.conftest  # noqa: F401
from app.core.crypto import decrypt_token, encrypt_token
from app.diagnosis.code_context import collect_context, render_slices
from app.diagnosis.code_diagnosis_agent import build_v2_prompt, parse_multifile
from app.engines.restart_manager import PROJECT_ROOT
from app.remediation import safe_patcher
from app.remediation.test_harness import run_custom_tests
from app.schemas import ServiceCreate


def _rmtree(path: Path) -> None:
    import stat

    def _onerr(func, p, _):
        try:
            import os
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, ignore_errors=False, onerror=_onerr)

V2_RAW = """<<<DIAGNOSIS>>>
Root Cause: helper returns None for missing keys
Upstream Origin: helpers.py:4
Crash Site: app.py:9
Remediation Strategy: guard with .get default
<<<END_DIAGNOSIS>>>

<<<PATCHES>>>
--- a/helpers.py
+++ b/helpers.py
@@ -1,3 +1,5 @@
 def rate(cfg):
-    return cfg["rate"]
+    return cfg.get("rate", 0)
<<<END_PATCHES>>>

<<<REGRESSION_TEST>>>
File: test_helpers_aeroops.py
Language: python
```test
from helpers import rate
def test_rate_default():
    assert rate({}) == 0
```test
<<<END_REGRESSION_TEST>>>"""


def test_crypto_roundtrip_and_refusals():
    enc = encrypt_token("ghp_secret123")
    assert enc.startswith("fernet:") and enc != "ghp_secret123"
    assert decrypt_token(enc) == "ghp_secret123"
    assert decrypt_token("") == ""
    assert decrypt_token("plaintext-evil") == ""
    assert encrypt_token("") == ""


def test_schema_guards():
    ok = ServiceCreate(name="x", test_command="pytest -q",
                       remediation_policy="MANUAL_APPROVAL")
    assert ok.test_command == "pytest -q"
    with pytest.raises(Exception):
        ServiceCreate(name="x", test_command="npm test; rm -rf /")
    with pytest.raises(Exception):
        ServiceCreate(name="x", remediation_policy="YOLO")


def _proj(files: dict, name: str = ".tmp-p3") -> Path:
    d = PROJECT_ROOT / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_context_collects_imports():
    d = _proj({"app.py": "from helpers import rate\n\nprint(rate({}))\n",
               "helpers.py": "def rate(cfg):\n    return cfg[\"rate\"]\n"})
    try:
        window, slices = collect_context(repo_root=d, target=d / "app.py", line=3)
        assert slices[0].primary and slices[0].path == "app.py"
        paths = [s.path for s in slices]
        assert "helpers.py" in paths, paths
        rendered = render_slices(slices)
        assert "PRIMARY CRASH FILE" in rendered and "def rate" in rendered
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_v2_prompt_and_parser():
    p = build_v2_prompt(service_name="s", incident_id=7,
                        runtime_error="KeyError", crash_locus="app.py:9",
                        stack_trace="tb", code_slices="code",
                        runtime_env="python", test_command="pytest -q")
    assert "[INCIDENT_ID]: 7" in p and "pytest -q" in p
    m = parse_multifile(V2_RAW)
    assert m and m.root_cause.startswith("helper returns None")
    assert m.upstream_origin == "helpers.py:4"
    assert len(m.patches) == 1 and "cfg.get" in m.patches[0]
    assert m.test and m.test.path == "test_helpers_aeroops.py"
    assert m.test.language == "python" and "def test_rate_default" in m.test.body
    assert parse_multifile("nothing here") is None
    assert parse_multifile("<<<DIAGNOSIS>>>\nRoot Cause: x\n<<<END_DIAGNOSIS>>>") is None


def test_apply_diffs_multi_and_limits():
    import subprocess as _sp
    d = PROJECT_ROOT / ".tmp-p3multi"
    if d.exists():
        _rmtree(d)
    d.mkdir()
    _sp.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    _sp.run(["git", "config", "user.email", "t@t.io"], cwd=d, check=True)
    _sp.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    (d / "a.py").write_text("x = 1\n")
    (d / "b.py").write_text("y = 2\n")
    _sp.run(["git", "add", "-A"], cwd=d, check=True)
    _sp.run(["git", "commit", "-qm", "i"], cwd=d, check=True)
    try:
        multi = ("--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 10\n"
                 "--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,1 @@\n-y = 2\n+y = 20\n")
        r = asyncio.run(safe_patcher.apply_diffs(repo=d, diff_text=multi))
        assert r.ok, r.detail
        assert (d / "a.py").read_text() == "x = 10\n"
        assert (d / "b.py").read_text() == "y = 20\n"
        big = "\n".join(f"--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
                        for i in range(6))
        r = asyncio.run(safe_patcher.apply_diffs(repo=d, diff_text=big))
        assert r.ok is False and "blast radius" in r.detail
    finally:
        _rmtree(d)


def test_custom_test_command_tier():
    d = _proj({"t.py": "x = 1\n"})
    try:
        ok = asyncio.run(safe_patcher_test_helper(d))
        assert ok
    finally:
        shutil.rmtree(d, ignore_errors=True)


async def safe_patcher_test_helper(d: Path) -> bool:
    from app.remediation.test_harness import verify_with_command
    good = await verify_with_command(
        target=d / "t.py", test_command="python --version", cwd=d)
    bad = await verify_with_command(
        target=d / "t.py", test_command="python -c \"import sys; sys.exit(3)\"", cwd=d)
    evil = await verify_with_command(
        target=d / "t.py", test_command="pytest; rm -rf /", cwd=d)
    return good.ok and not bad.ok and not evil.ok


def test_push_without_token_or_remote_is_safe():
    import asyncio as _aio
    from app.remediation import git_workspace
    d = _proj({"f.txt": "x\n"})
    try:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
        code, _ = _aio.run(git_workspace._git(d, "push", "-u", "origin", "main"))
        assert code != 0  # no remote: must fail, never hang the suite
    finally:
        shutil.rmtree(d, ignore_errors=True)
