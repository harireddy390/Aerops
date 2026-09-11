"""Multi-file context collection: the crash locus plus the helpers it imports.

Reads the primary file's ±20-line window, scans its imports, and pulls
targeted slices (definition ±15 lines) of up to 3 related files inside the
repo. Everything is size-capped so small models stay in context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILES = 4  # primary + 3 related
MAX_CHARS = 6000

PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w\s,()]+)|import\s+([\w.]+))", re.M)
JS_IMPORT = re.compile(r"""(?:import\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\))""")
DEF_LINE = re.compile(r"^\s*(?:def\s+(\w+)|(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)")


@dataclass
class CodeSlice:
    path: str  # repo-relative display path
    content: str
    primary: bool = False


def _resolve_import(base_dir: Path, repo: Path, raw: str) -> Path | None:
    raw = raw.strip()
    if not raw or raw.startswith((".", "/", "http", "@", "node:")):
        if raw.startswith("."):
            cand = (base_dir / raw).resolve()
            for ext in ("", ".py", ".js", ".jsx", ".ts", ".tsx", "/index.py",
                        "/index.js", "/index.ts"):
                p = Path(str(cand) + ext) if ext and not raw.endswith("/") else cand
                if p.is_file() and (repo in p.parents or p == repo):
                    return p
        return None
    # bare module: search repo (skip heavy dirs), unique match only
    found = [p for p in repo.rglob(raw.split(".")[-1] + ".py")
             if p.is_file() and not any(part in ("node_modules", ".git", "dist", "__pycache__") for part in p.parts)]
    mods = [p for p in repo.rglob(raw.split("/")[-1] + ".js")
            if p.is_file() and not any(part in ("node_modules", ".git", "dist") for part in p.parts)]
    found.extend(mods)
    unique = sorted(set(found))
    return unique[0] if len(unique) == 1 else None


def _slice_around(path: Path, symbol: str | None, radius: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    start = 0
    if symbol:
        for i, line in enumerate(lines):
            m = DEF_LINE.match(line)
            if m and symbol in (m.group(1), m.group(2), m.group(3)):
                start = max(0, i - radius)
                break
    window = lines[start:start + radius * 2]
    return "\n".join(window)[:2000]


def collect_context(*, repo_root: Path, target: Path, line: int,
                    radius: int = 20) -> tuple[str, list[CodeSlice]]:
    """Returns (numbered_primary_window, slices). Slices[0] is always primary."""
    from app.remediation.safe_patcher import read_context
    primary = read_context(target, max(line, 1), radius=radius)
    try:
        rel = target.relative_to(repo_root).as_posix()
    except ValueError:
        rel = target.name
    slices = [CodeSlice(path=rel, content=primary, primary=True)]
    try:
        text = target.read_text(errors="replace")
    except OSError:
        return primary, slices
    wanted: list[tuple[str, str | None]] = []  # (module, symbol)
    if target.suffix == ".py":
        for mod, names, bare in PY_IMPORT.findall(text):
            if bare and not bare.split(".")[0] in ("os", "sys", "json", "re", "time",
                                                   "pathlib", "typing", "datetime"):
                wanted.append((bare, None))
            elif mod and not mod.startswith(".") and "." not in mod:
                wanted.append((mod, None))
            elif mod.startswith("."):
                for nm in names.replace("(", " ").replace(")", " ").replace(",", " ").split():
                    if nm and nm != "*":
                        wanted.append((mod, nm))
    else:
        for rel_imp, req in JS_IMPORT.findall(text):
            raw = rel_imp or req
            if raw and not raw.startswith(("@", "node:")) and "://" not in raw:
                wanted.append((raw, None))
    seen: set[str] = set()
    for raw, symbol in wanted:
        resolved = _resolve_import(target.parent, repo_root, raw)
        if not resolved or str(resolved) in seen:
            continue
        seen.add(str(resolved))
        try:
            disp = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        content = _slice_around(resolved, symbol, 15)
        if content:
            slices.append(CodeSlice(path=disp, content=content))
        if len(slices) >= MAX_FILES:
            break
    total = sum(len(s.content) for s in slices)
    if total > MAX_CHARS:
        # trim related files first, never the primary window
        budget = MAX_CHARS - len(slices[0].content)
        for s in slices[1:]:
            keep = max(0, min(len(s.content), budget // max(1, len(slices) - 1)))
            s.content = s.content[:keep]
    return primary, slices


def render_slices(slices: list[CodeSlice]) -> str:
    parts = []
    for s in slices:
        tag = "PRIMARY CRASH FILE" if s.primary else "RELATED FILE"
        parts.append(f"--- {tag}: {s.path} ---\n{s.content}")
    return "\n\n".join(parts)[:MAX_CHARS]


@dataclass
class WalkResult:
    primary_window: str
    slices: list[CodeSlice] = field(default_factory=list)
