"""Tests for resilient multi-tier safe patcher and fuzzy context fallback."""
import asyncio
import subprocess
from pathlib import Path
import pytest

from app.remediation.safe_patcher import apply_diff, _apply_fuzzy_fallback


def test_fuzzy_fallback_replaces_drifted_context(tmp_path: Path):
    # Setup a sample repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@aeroops.io"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)

    target_file = repo / "app.js"
    target_file.write_text(
        "const express = require('express');\n"
        "const app = express();\n"
        "// BUG: missing port config\n"
        "const port = undefined;\n"
        "app.listen(port, () => console.log('Listening'));\n"
    )
    subprocess.run(["git", "add", "app.js"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    # Diff with totally wrong line numbers and hallucinated context lines
    drifted_diff = (
        "--- a/app.js\n"
        "+++ b/app.js\n"
        "@@ -99,10 +99,10 @@ function startServer() {\n"
        "-// BUG: missing port config\n"
        "-const port = undefined;\n"
        "+const port = process.env.PORT || 3000;\n"
        " console.log('started');\n"
    )

    # Apply via apply_diff (which triggers Pass 5 fuzzy fallback)
    res = asyncio.run(apply_diff(repo=repo, diff_text=drifted_diff))
    assert res.ok is True, res.detail
    assert "fuzzy context match" in res.detail

    updated_content = target_file.read_text()
    assert "const port = process.env.PORT || 3000;" in updated_content
    assert "const port = undefined;" not in updated_content
