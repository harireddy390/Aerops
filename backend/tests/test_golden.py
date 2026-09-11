"""Golden-path tests: parser, diff apply, test materialization, reflexion, e2e."""
import asyncio
import shutil
import subprocess
from pathlib import Path

import tests.conftest  # noqa: F401
from app.diagnosis.code_diagnosis_agent import build_golden_prompt, parse_golden
from app.diagnosis.reflexion_agent import propose_golden_with_reflexion
from app.engines.restart_manager import PROJECT_ROOT
from app.remediation import safe_patcher

DIFF_OK = """--- a/w.js
+++ b/w.js
@@ -1,2 +1,2 @@
-const n = user.profile.name;
+const n = user?.profile?.name ?? 'guest';
 console.log(n);
"""

RAW_GOLDEN = """<<<DIAGNOSIS>>>
Root Cause: user.profile is undefined when user has no profile
Failure Line: w.js:1
Strategy: guard with optional chaining and default
<<<END_DIAGNOSIS>>>

<<<PATCH>>>
--- a/w.js
+++ b/w.js
@@ -1,2 +1,2 @@
-const n = user.profile.name;
+const n = user?.profile?.name ?? 'guest';
 console.log(n);
<<<END_PATCH>>>

<<<TEST_SUITE_SUGGESTION>>>
const n = undefined?.profile?.name ?? 'guest';
if (n !== 'guest') throw new Error('guard failed');
<<<END_TEST_SUITE_SUGGESTION>>>"""


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


def _repo(files: dict, name: str = ".tmp-goldentest") -> Path:
    d = PROJECT_ROOT / name
    if d.exists():
        _rmtree(d)
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    for name, content in files.items():
        (d / name).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True)
    return d


def test_golden_prompt_and_parser():
    p = build_golden_prompt(service_name="s", error_message="boom",
                            stack_trace="TypeError x", file_path="w.js",
                            file_content="1 | const a = 1;")
    assert "INPUT CONTRACT" in p and "w.js" in p
    g = parse_golden(RAW_GOLDEN)
    assert g and g.root_cause.startswith("user.profile")
    assert g.failure_line == "w.js:1"
    assert "@@" in g.diff_text and "guest" in g.test_suggestion
    messy = "Sure thing!\n```diff\n" + RAW_GOLDEN + "\n```\nHope this helps"
    assert parse_golden(messy).root_cause.startswith("user.profile")
    assert parse_golden("no blocks here") is None
    assert parse_golden("<<<DIAGNOSIS>>>\nRoot Cause: x\n<<<END_DIAGNOSIS>>>") is None


def test_apply_diff_and_traversal_guard():
    d = _repo({"w.js": "const n = user.profile.name;\nconsole.log(n);\n"})
    try:
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text=DIFF_OK))
        assert r.ok, r.detail
        assert "?? 'guest'" in (d / "w.js").read_text()
        evil = DIFF_OK.replace("a/w.js", "a/../../evil.js").replace("b/w.js", "b/../../evil.js")
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text=evil))
        assert r.ok is False and "escapes" in r.detail
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text="not a diff"))
        assert r.ok is False
    finally:
        _rmtree(d)


def test_apply_diff_honors_crlf_files():
    import subprocess as _sp
    d = _repo({"c.txt": "alpha\nbeta\n"}, ".tmp-golden3")
    try:
        _sp.run(["git", "config", "core.autocrlf", "false"], cwd=d, check=True)
        (d / "c.txt").write_bytes(b"alpha\r\nbeta\r\n")
        _sp.run(["git", "add", "-A"], cwd=d, check=True)
        _sp.run(["git", "commit", "-qm", "crlf"], cwd=d, check=True)
        lf_diff = ("--- a/c.txt\n+++ b/c.txt\n@@ -99,1 +99,1 @@\n-alpha\n+alpha fixed\n")
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text=lf_diff))
        assert r.ok, r.detail
        assert "alpha fixed" in (d / "c.txt").read_text()
    finally:
        _rmtree(d)


def test_apply_diff_renumbers_drifted_hunks():
    src = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n"
    d = _repo({"f.txt": src})
    try:
        drifted = ("--- a/f.txt\n+++ b/f.txt\n"
                   "@@ -99,3 +99,3 @@\n line8\n-line9\n+line9 fixed\n line10\n")
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text=drifted))
        assert r.ok, r.detail
        assert "line9 fixed" in (d / "f.txt").read_text()
        # ambiguous content still aborts
        d2 = _repo({"g.txt": "same\nsame\n"}, ".tmp-golden2")
        try:
            dup = ("--- a/g.txt\n+++ b/g.txt\n@@ -1,1 +1,1 @@\n-same\n+diff\n")
            r = asyncio.run(safe_patcher.apply_diff(repo=d2, diff_text=dup))
            assert r.ok is False
        finally:
            _rmtree(d2)
    finally:
        _rmtree(d)


def test_apply_diff_ignores_trailing_separator():
    src = "one\ntwo\n"
    d = _repo({"h.txt": src}, ".tmp-golden4")
    try:
        debris = ("--- a/h.txt\n+++ b/h.txt\n@@ -99,1 +99,1 @@\n-one\n+one fixed\n---\n")
        r = asyncio.run(safe_patcher.apply_diff(repo=d, diff_text=debris))
        assert r.ok, r.detail
        assert "one fixed" in (d / "h.txt").read_text()
    finally:
        _rmtree(d)


def test_materialize_test_namespaced():
    d = _repo({"w.js": "x\n"})
    try:
        target = d / "w.js"
        p = safe_patcher.materialize_test(target=target, suggestion="assert (1 + 1) === 2;", language="javascript")
        assert p and p.name == "w.aeroops.test.js" and p.exists()
        assert safe_patcher.materialize_test(target=target, suggestion="assert (2 + 2) === 4;", language="javascript") is None
        assert safe_patcher.materialize_test(target=target, suggestion="x", language="brainfuck") is None
    finally:
        _rmtree(d)


def test_golden_reflexion_loop():
    from app.diagnosis.code_diagnosis_agent import GoldenProposal

    async def propose_fn():
        return (GoldenProposal(root_cause="r", diff_text="d", test_suggestion="t"), "mock")

    async def ok_patch(p):
        return True, ""

    out = asyncio.run(propose_golden_with_reflexion(
        propose_fn, error="boom", context_block="a", try_patch=ok_patch))
    assert out[2] == "verified" and out[1] == "mock"

    import unittest.mock as mock
    import app.diagnosis.code_diagnosis_agent as agent_mod

    async def fake_golden(prompt):
        return ('<<<DIAGNOSIS>>>\nRoot Cause: r2\n<<<END_DIAGNOSIS>>>\n'
                '<<<PATCH>>>\n--- a/w\n+++ b/w\n@@ -1 +1 @@\n-a\n+b\n<<<END_PATCH>>>')

    async def fake_ollama(prompt):
        return None

    tries = []

    async def always_fail(p):
        tries.append(1)
        return False, "nope"

    with mock.patch.object(agent_mod, "_ask_openai_golden", side_effect=fake_golden), \
         mock.patch.object(agent_mod, "_ask_ollama_golden", side_effect=fake_ollama):
        out = asyncio.run(propose_golden_with_reflexion(
            propose_fn, error="boom", context_block="a", try_patch=always_fail))
    assert out[2] == "escalated" and len(tries) == 3


def test_golden_pipeline_e2e_mocked(monkeypatch):
    import app.remediation.code_pipeline as pipe
    from app.db.database import SessionLocal, init_db
    from app.db.models import Service
    from app.diagnosis.code_diagnosis_agent import MultiProposal, RegressionTest
    from app.engines import incident_engine
    init_db()
    d = _repo({"w.js": "const n = user.profile.name;\nconsole.log(n);\n"})
    db = SessionLocal()
    try:
        svc = Service(name="goldene2e", command="node w.js",
                      working_directory=".tmp-goldentest", auto_remediation=True,
                      policy_mode="DRAFT_PR")
        db.add(svc)
        db.commit()
        inc = incident_engine.create_incident(db, service_id=svc.id, type="frontend",
                                              severity="critical", error_message="TypeError x",
                                              fingerprint="beef01")
        db.commit()
        iid = inc.id

        async def fake_multi(**kwargs):
            return (MultiProposal(
                root_cause="null deref", upstream_origin="N/A - Direct Call",
                crash_site="w.js:1", strategy="guard",
                patches=[DIFF_OK],
                test=RegressionTest(path="w.check.aeroops.test.js",
                                    language="javascript",
                                    body="const n = undefined?.profile?.name ?? 'guest';\n"
                                         "if (n !== 'guest') throw new Error('x');\n")), "mock:test")
        monkeypatch.setattr(pipe, "propose_multifile", fake_multi)
        calls = []

        async def fake_draft(db, ws, **kw):
            calls.append(kw)
            return "PR-BODY"
        monkeypatch.setattr(pipe.delivery_gate, "deliver_draft_pr", fake_draft)
        asyncio.run(pipe.run_code_remediation(iid, "w.js", 1))
        assert "?? 'guest'" in (d / "w.js").read_text()
        assert (d / "w.check.aeroops.test.js").exists()
        assert calls and calls[0]["diff_stat"]
        db.refresh(inc)
    finally:
        db.close()
        _rmtree(d)
