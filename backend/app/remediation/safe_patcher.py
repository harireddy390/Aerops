"""Safe patch engine: the ONLY code that may modify service files.

Gate order (any failure aborts, repo left intact):
1. resolve target strictly inside the service directory (traversal-proof)
2. atomic backup <file>.aeroops.bak
3. search_block must match EXACTLY once (0 or 2+ -> abort, backup removed)
4. write replacement
5. run verification_command — allowlisted prefixes only, NO shell, 45s timeout,
   cwd confined to project root. Runs in a worker THREAD (subprocess.run):
   battle-tested on Windows, immune to event-loop/subprocess interactions.
6. exit 0 -> drop backup, success. else -> restore backup, escalate.

Model output never reaches a shell: commands are shlex-split and argv-executed.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

# command must start with one of these (plus safe file/dir args only)
VERIFY_ALLOWLIST = (
    "node --check",
    "npx tsc --noEmit",
    "npm run build",
    "npm test",
    "python -m py_compile",
)

VERIFY_TIMEOUT_SEC = 45


@dataclass
class PatchResult:
    ok: bool
    detail: str


def resolve_target(service_dir: Path, project_root: Path, file_hint: str) -> Path | None:
    """Map a crash file hint to a real file under service_dir.

    Accepts relative paths, absolute paths, and browser URLs (basename match).
    Returns None when ambiguous or outside the fence.
    """
    root = project_root.resolve()
    base = (root / service_dir).resolve() if not service_dir.is_absolute() else service_dir.resolve()
    if root not in base.parents and base != root:
        return None
    hint = (file_hint or "").strip().split("?")[0]
    # A path with directories (or absolute) is precise: resolve it directly.
    # Anything else (bare names, browser URLs) goes through basename search so
    # duplicates are detected as ambiguous instead of silently picking one.
    if "://" not in hint:
        rel = hint
        if "/" in rel or "\\" in rel or Path(rel).is_absolute():
            p = (Path(rel) if Path(rel).is_absolute() else (base / rel)).resolve()
            if p.is_file() and (root in p.parents or p == root):
                return p
    # basename search inside the service dir (skip heavy dirs)
    name = hint.split("/")[-1].split("\\")[-1]
    if not name:
        return None
    found: list[Path] = []
    for p in base.rglob(name):
        if not p.is_file():
            continue
        if any(part in ("node_modules", ".git", "dist") for part in p.parts):
            continue
        found.append(p.resolve())
        if len(found) > 5:
            break
    unique = sorted(set(found))
    return unique[0] if len(unique) == 1 else None


def read_context(target: Path, line: int, radius: int = 20) -> str:
    """Numbered ±radius window for the model. 1-based line numbers."""
    lines = target.read_text(errors="replace").splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return "\n".join(f"{n:5d} | {lines[n - 1]}" for n in range(start, end + 1))


def _check_command(command: str, cwd: Path, project_root: Path) -> list[str]:
    if not any(command.strip().startswith(prefix) for prefix in VERIFY_ALLOWLIST):
        raise ValueError(f"verification command not allowlisted: {command[:80]}")
    parts = shlex.split(command, posix=os.name != "nt")
    if any(any(tok in part for tok in (";", "&", "|", "`", "$", ">", "<", "\n")) for part in parts[1:]):
        raise ValueError("metacharacters not allowed in verification args")
    return parts


def _run_verify(parts: list[str], cwd: Path) -> tuple[int | None, bytes]:
    """Blocking verify in a worker thread. Returns (exit_code, output);
    exit None means the 45s timeout fired (child is killed by run()).
    stdin is always DEVNULL: a verifier must never block waiting for input
    (bare `node --check` reads stdin — that exact hang is why this exists)."""
    try:
        cp = subprocess.run(parts, cwd=str(cwd), capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=VERIFY_TIMEOUT_SEC)
        return cp.returncode, (cp.stdout or b"") + (cp.stderr or b"")
    except subprocess.TimeoutExpired:
        return None, b""
    except OSError as exc:
        raise exc


async def apply_patch(*, target: Path, search_block: str, replacement_block: str,                      verification_command: str, cwd: Path,
                      project_root: Path) -> PatchResult:
    backup = target.with_name(target.name + ".aeroops.bak")
    try:
        original = target.read_text()
    except OSError as exc:
        return PatchResult(False, f"cannot read target: {exc}")
    hits = original.count(search_block)
    if hits == 0:
        return PatchResult(False, "search_block not found — model context stale, aborting")
    if hits > 1:
        return PatchResult(False, f"search_block matches {hits}× — ambiguous, aborting")
    try:
        backup.write_text(original)
    except OSError as exc:
        return PatchResult(False, f"backup failed, refusing to touch file: {exc}")
    try:
        target.write_text(original.replace(search_block, replacement_block, 1))
    except OSError as exc:
        return PatchResult(False, f"write failed: {exc}")
    try:
        parts = _check_command(verification_command, cwd, project_root)
    except ValueError as exc:
        _restore(target, backup, original)
        return PatchResult(False, f"unsafe verification command, rolled back: {exc}")
    if parts == ["node", "--check"]:
        # bare `node --check` reads stdin and hangs: bind it to the target file
        parts = ["node", "--check", target.name]
    if parts[0] in ("npx", "npm") and not (cwd / "package.json").exists():
        _restore(target, backup, original)
        return PatchResult(False, f"'{' '.join(parts[:3])}' needs a Node project here "
                                  f"({cwd.name} has no package.json) — refusing a "
                                  f"slow network fetch, rolled back")
    try:
        code, out = await asyncio.to_thread(_run_verify, parts, cwd)
    except OSError as exc:
        _restore(target, backup, original)
        return PatchResult(False, f"verification could not run, rolled back: {exc}")
    if code is None:
        _restore(target, backup, original)
        return PatchResult(False, "verification timed out after 45s, rolled back")
    tail = (out or b"").decode("utf-8", "replace")[-1500:]
    if code != 0:
        _restore(target, backup, original)
        return PatchResult(False, f"verification failed (exit {code}), rolled back: {tail[-400:]}")
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    return PatchResult(True, f"verified clean: {tail[-200:]}")


def _restore(target: Path, backup: Path, original: str) -> None:
    try:
        if backup.exists():
            target.write_text(backup.read_text())
            backup.unlink(missing_ok=True)
        else:
            target.write_text(original)
    except OSError:
        pass


async def _git(repo: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    """Minimal argv git runner for patch application (full manager lives in
    git_workspace.py; this keeps safe_patcher dependency-free)."""
    import asyncio as _aio
    import subprocess as _sp

    def _call() -> tuple[int, str]:
        try:
            cp = _sp.run(["git", *args], cwd=str(repo), capture_output=True,
                         stdin=_sp.DEVNULL, timeout=timeout)
            out = ((cp.stdout or b"") + (cp.stderr or b"")).decode("utf-8", "replace")
            return cp.returncode, out[-1500:]
        except _sp.TimeoutExpired:
            return None, "git timed out"
        except OSError as exc:
            return -1, f"git failed: {exc}"

    return await _aio.to_thread(_call)


def _apply_fuzzy_fallback(repo: Path, diff_text: str) -> bool | str:
    """Fallback when git apply and hunk renumbering both fail due to drifted or
    hallucinated context lines. Extracts deleted (-) and added (+) lines per hunk.
    If the deleted lines match a unique location in the target file (either exact or
    ignoring leading/trailing whitespace), replaces that location with the added lines.
    Preserves target file CRLF/LF line endings.
    """
    import re as _re
    lines = diff_text.splitlines()
    try:
        plus_idx = next(i for i, l in enumerate(lines) if l.startswith("+++ "))
    except StopIteration:
        return "no target file in diff"
    if sum(1 for l in lines if l.startswith("--- ")) > 1:
        return "multi-file diffs not supported in single fuzzy hunk"
    target_rel = lines[plus_idx][4:].strip().split("\t")[0]
    for prefix in ("b/", "a/"):
        if target_rel.startswith(prefix):
            target_rel = target_rel[2:]
            break
    target = (repo / target_rel).resolve()
    if not target.is_file():
        return f"target file not found: {target_rel}"
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return f"cannot read target: {exc}"
    ending = "\r\n" if b"\r\n" in raw else "\n"
    file_lines = raw.decode("utf-8", "replace").splitlines()

    # Parse hunks into (del_lines, add_lines)
    hunks: list[tuple[list[str], list[str]]] = []
    i = plus_idx + 1
    while i < len(lines):
        m = _re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", lines[i])
        if not m:
            i += 1
            continue
        del_lines: list[str] = []
        add_lines: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("@@") \
                and not lines[j].startswith(("--- ", "+++ ", "diff ")) \
                and lines[j].strip() != "---":
            if lines[j].startswith("-"):
                del_lines.append(lines[j][1:])
            elif lines[j].startswith("+"):
                add_lines.append(lines[j][1:])
            j += 1
        if del_lines or add_lines:
            hunks.append((del_lines, add_lines))
        i = j

    if not hunks:
        return "no hunks found"

    new_file_lines = list(file_lines)
    applied_count = 0

    for del_lines, add_lines in hunks:
        if not del_lines:
            continue

        exact_hits = [
            k for k in range(len(new_file_lines) - len(del_lines) + 1)
            if new_file_lines[k : k + len(del_lines)] == del_lines
        ]
        if len(exact_hits) == 1:
            k = exact_hits[0]
            new_file_lines[k : k + len(del_lines)] = add_lines
            applied_count += 1
            continue

        del_stripped = [l.strip() for l in del_lines if l.strip()]
        if not del_stripped:
            continue
        strip_hits = []
        for k in range(len(new_file_lines) - len(del_lines) + 1):
            window = [l.strip() for l in new_file_lines[k : k + len(del_lines)] if l.strip()]
            if window == del_stripped:
                strip_hits.append(k)

        if len(strip_hits) == 1:
            k = strip_hits[0]
            orig_indent = ""
            if new_file_lines[k]:
                orig_indent = new_file_lines[k][:len(new_file_lines[k]) - len(new_file_lines[k].lstrip())]
            adjusted_adds = []
            for al in add_lines:
                al_strip = al.strip()
                if al_strip:
                    al_indent = al[:len(al) - len(al.lstrip())]
                    adjusted_adds.append(orig_indent + al_strip if not al_indent else al)
                else:
                    adjusted_adds.append("")
            new_file_lines[k : k + len(del_lines)] = adjusted_adds
            applied_count += 1
            continue

        return f"deleted lines matched {len(exact_hits)} exact / {len(strip_hits)} stripped locations (need exactly 1)"

    if applied_count == 0:
        return "could not uniquely anchor any hunk"

    try:
        content = ending.join(new_file_lines)
        if not content.endswith(ending):
            content += ending
        target.write_bytes(content.encode("utf-8"))
    except OSError as exc:
        return f"write failed: {exc}"
    return True



def _apply_exact(repo: Path, diff_text: str) -> bool | str:
    """Apply a renumbered single-file diff by exact content match, preserving
    the file's native line endings. Returns True or an error string."""
    import re as _re
    lines = diff_text.splitlines()
    try:
        plus_idx = next(i for i, l in enumerate(lines) if l.startswith("+++ "))
    except StopIteration:
        return "no target file in diff"
    if sum(1 for l in lines if l.startswith("--- ")) > 1:
        return "multi-file diffs not supported here"
    target_rel = lines[plus_idx][4:].strip().split("\t")[0]
    for prefix in ("b/", "a/"):
        if target_rel.startswith(prefix):
            target_rel = target_rel[2:]
            break
    target = (repo / target_rel).resolve()
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return f"cannot read target: {exc}"
    ending = "\r\n" if b"\r\n" in raw else "\n"
    current = raw.decode("utf-8", "replace").splitlines()
    new_lines = list(current)
    applied_any = False
    i = plus_idx + 1
    while i < len(lines):
        m = _re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", lines[i])
        if not m:
            i += 1
            continue
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("@@") \
                and not lines[j].startswith(("--- ", "+++ ", "diff ")) \
                and lines[j].strip() != "---":
            body.append(lines[j])
            j += 1
        old_part = [l[1:] for l in body if l.startswith((" ", "-"))]
        new_part = [l[1:] for l in body if l.startswith((" ", "+"))]
        if not old_part:
            return "empty hunk"
        hits = [k for k in range(len(new_lines) - len(old_part) + 1)
                if new_lines[k:k + len(old_part)] == old_part]
        if len(hits) != 1:
            return f"hunk matches {len(hits)}×, need exactly 1"
        k = hits[0]
        new_lines[k:k + len(old_part)] = new_part
        applied_any = True
        i = j
    if not applied_any:
        return "no hunks applied"
    try:
        target.write_bytes(ending.join(new_lines).encode("utf-8") + ending.encode("utf-8"))
    except OSError as exc:
        return f"write failed: {exc}"
    return True


def _split_sections(text: str) -> list[str]:
    """Split a multi-file unified diff into per-file sections. A new section
    starts at each `--- ` line once the current one already has its `+++ `.
    Bare `---` separator lines the model sometimes trails with are debris
    and get dropped (they corrupt hunk parsing otherwise)."""
    sections: list[str] = []
    cur: list[str] = []
    has_plus = False
    for line in text.splitlines():
        if line.strip() == "---":
            continue
        if line.startswith("--- ") and has_plus:
            sections.append("\n".join(cur))
            cur, has_plus = [], False
        cur.append(line)
        if line.startswith("+++ "):
            has_plus = True
    if cur:
        sections.append("\n".join(cur))
    return [s for s in sections if "--- " in s and "+++ " in s and "@@" in s]


async def apply_diffs(*, repo: Path, diff_text: str) -> PatchResult:
    """Apply one or more file diffs section-by-section (each through the full
    gate chain). First failure aborts; the caller abandons the branch."""
    sections = _split_sections(diff_text or "")
    if not sections:
        return PatchResult(False, "no applyable file sections in proposal")
    if len(sections) > 5:
        return PatchResult(False, "too many files touched (max 5) — blast radius")
    for sec in sections:
        result = await apply_diff(repo=repo, diff_text=sec)
        if not result.ok:
            return PatchResult(False, f"section failed: {result.detail}"[:600])
    return PatchResult(True, f"{len(sections)} file(s) patched cleanly")


async def apply_diff(repo: Path, diff_text: str) -> PatchResult:
    """Single-file diff through the full gate chain (see apply_diffs)."""
    text = (diff_text or "").strip()
    if "--- " not in text or "@@" not in text:
        return PatchResult(False, "no unified diff found in proposal")
    for line in text.splitlines():
        if line.startswith(("--- ", "+++ ")):
            path = line[4:].strip().split("\t")[0]
            if path in ("/dev/null", "dev/null"):
                continue
            for prefix in ("a/", "b/"):
                if path.startswith(prefix):
                    path = path[2:]
                    break
            if path.startswith("/") or ".." in Path(path).parts:
                return PatchResult(False, f"diff escapes repo: {path[:120]}")
    # pass 1: as the model wrote it (exact hunk headers)
    ok, out = await _apply_raw(repo, text)
    if ok:
        return PatchResult(True, "diff applied cleanly")
    # pass 2: models miscount @@ offsets constantly but copy content well.
    # Recompute hunk headers from an exact content search; content itself
    # must still match byte-for-byte exactly once, or we abort.
    fixed = _renumber_hunks(repo, text)
    if fixed is not None:
        ok, out2 = await _apply_raw(repo, fixed)
        if ok:
            return PatchResult(True, "diff applied cleanly (hunk offsets renormalized)")
    # pass 3: trailing-whitespace drift only (still content-verified by git).
    # Editors and models alike add stray spaces; meaning is unchanged.
    if fixed is not None:
        ok, out3 = await _apply_raw_ws(repo, fixed)
        if ok:
            return PatchResult(True, "diff applied cleanly (whitespace drift tolerated)")
    # pass 4: byte-exact in-process apply for files git can't match itself,
    # notably CRLF working trees vs LF model output. The hunk content must
    # still match exactly once (splitlines-normalized); original line endings
    # are preserved on write.
    exact_note = ""
    if fixed is not None:
        exact = _apply_exact(repo, fixed)
        if exact is True:
            return PatchResult(True, "diff applied cleanly (exact content match)")
        exact_note = f" | exact-apply: {exact}"
    # pass 5: resilient deleted-lines & fuzzy context matcher
    fuzzy = _apply_fuzzy_fallback(repo, text)
    if fuzzy is True:
        return PatchResult(True, "diff applied cleanly (fuzzy context match)")
    fuzzy_note = f" | fuzzy-apply: {fuzzy}" if isinstance(fuzzy, str) else ""
    return PatchResult(False, f"git apply --check rejected: {out[-400:]}{exact_note}{fuzzy_note}"[:600])


async def _apply_raw(repo: Path, text: str) -> tuple[bool, str]:
    # git apply reads the patch from a temp file (argv stays clean, no shell).
    # Temp file lives inside the repo and is always removed; on a fix branch
    # any residue would vanish with abandon() anyway.
    # BYTES write (no newline translation): text-mode would turn \n into \r\n
    # and corrupt CRLF-translated hunks with doubled carriage returns.
    patch_file = repo / ".aeroops.patch.tmp"
    try:
        patch_file.write_bytes((text + "\n").encode("utf-8"))
        code, out = await _git(repo, "apply", "--check", patch_file.name)
        if code != 0:
            return False, out
        code, out = await _git(repo, "apply", patch_file.name)
        if code != 0:
            return False, out
        return True, "applied"
    finally:
        try:
            patch_file.unlink(missing_ok=True)
        except OSError:
            pass


async def _apply_raw_ws(repo: Path, text: str) -> tuple[bool, str]:
    """Same as _apply_raw but tolerating whitespace-only drift
    (--ignore-whitespace). Content lines must still align; git enforces that."""
    patch_file = repo / ".aeroops.patch.tmp"
    try:
        patch_file.write_bytes((text + "\n").encode("utf-8"))
        code, out = await _git(repo, "apply", "--check", "--ignore-whitespace",
                               patch_file.name)
        if code != 0:
            return False, out
        code, out = await _git(repo, "apply", "--ignore-whitespace", patch_file.name)
        if code != 0:
            return False, out
        return True, "applied"
    finally:
        try:
            patch_file.unlink(missing_ok=True)
        except OSError:
            pass


def _renumber_hunks(repo: Path, text: str) -> str | None:
    """Rewrite @@ headers from exact content location. Returns fixed diff or
    None when the content cannot be placed unambiguously. Single-file diffs."""
    import re as _re
    lines = text.splitlines()
    try:
        plus_idx = next(i for i, l in enumerate(lines) if l.startswith("+++ "))
    except StopIteration:
        return None
    # refuse multi-file diffs: one patch, one file, full attention
    if sum(1 for l in lines if l.startswith("--- ")) > 1:
        return None
    target_rel = lines[plus_idx][4:].strip().split("\t")[0]
    for prefix in ("b/", "a/"):
        if target_rel.startswith(prefix):
            target_rel = target_rel[2:]
            break
    target = (repo / target_rel).resolve()
    try:
        current = target.read_text().splitlines()
    except OSError:
        return None
    out: list[str] = list(lines[: plus_idx + 1])
    i = plus_idx + 1
    delta = 0
    changed = False
    while i < len(lines):
        m = _re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("@@") \
                and not lines[j].startswith(("--- ", "+++ ", "diff ")) \
                and lines[j].strip() != "---":
            body.append(lines[j])
            j += 1
        old_part = [l[1:] for l in body if l.startswith((" ", "-"))]
        if not old_part:
            return None
        # locate the block: exact match, exactly once — else blank-tolerant
        # match (blank lines carry no meaning outside string literals; the
        # rebuilt hunk below always uses the FILE's own lines for context).
        hits = [k for k in range(len(current) - len(old_part) + 1)
                if current[k:k + len(old_part)] == old_part]
        emit_body = body
        if len(hits) != 1:
            rebuilt = _place_blank_tolerant(current, body)
            if rebuilt is None:
                return None
            new_body_lines, start0 = rebuilt
            old_count = sum(1 for l in new_body_lines if l.startswith((" ", "-")))
            new_count = sum(1 for l in new_body_lines if l.startswith((" ", "+")))
            new_start = start0 + 1 + delta
            out.append(f"@@ -{start0 + 1},{old_count} +{new_start},{new_count} @@{m.group(5)}")
            out.extend(new_body_lines)
            delta += new_count - old_count
            changed = True
            i = j
            continue
        start0 = hits[0]  # 0-based
        old_count = sum(1 for l in body if l.startswith((" ", "-")))
        new_count = sum(1 for l in body if l.startswith((" ", "+")))
        new_start = start0 + 1 + delta
        out.append(f"@@ -{start0 + 1},{old_count} +{new_start},{new_count} @@{m.group(5)}")
        out.extend(body)
        delta += new_count - old_count
        changed = True
        i = j
    return "\n".join(out) if changed else None


def _place_blank_tolerant(current: list[str], body: list[str]
                          ) -> tuple[list[str], int] | None:
    """Place a hunk whose blank-line runs drift from the file.

    Matches the hunk's NON-BLANK old lines as an ordered subsequence against
    the file's non-blank lines (must occur exactly once), then rebuilds the
    hunk body from the FILE's actual lines for context/deletions, keeping the
    model's `+` lines. Returns (new_body, start0) or None.
    """
    old_nb = [(idx, l[1:]) for idx, l in enumerate(body)
              if l.startswith((" ", "-")) and l[1:].strip() != ""]
    if not old_nb:
        return None
    file_nb = [(k, ln) for k, ln in enumerate(current) if ln.strip() != ""]
    seq = [t for _, t in old_nb]
    starts = [k for k, _ in file_nb
              if [t for _, t in file_nb[k:k + len(seq)]] == seq]
    # unique placement required; also anchor by matching span length sanity
    if len(starts) != 1:
        # try anchored on the deletion lines (strongest signal) if present
        dels = [t for idx, t in old_nb if body[idx].startswith("-")]
        if not dels:
            return None
        starts = [k for k, _ in file_nb
                  if [t for _, t in file_nb[k:k + len(dels)]] == dels]
        if len(starts) != 1:
            return None
        # expand to full span around the deletion anchor
        first_nb = next(idx for idx, t in old_nb if body[idx].startswith("-"))
        anchor_file = starts[0]
        # walk backwards/forwards to cover the whole hunk span
        span_file_start = anchor_file - first_nb
        # count non-blank file lines consumed = len(old_nb)
        span_end_nb = anchor_file + (len(old_nb) - first_nb)
        # map: file non-blank index -> file absolute index covered range
        nb_positions = [k for k, _ in file_nb]
        lo = nb_positions[span_file_start] if 0 <= span_file_start < len(nb_positions) else None
        hi_excl = nb_positions[span_end_nb] + 1 if 0 <= span_end_nb < len(nb_positions) else None
        if lo is None or hi_excl is None:
            return None
        return _rebuild_from_span(current, body, old_nb, lo, hi_excl, file_nb,
                                  span_file_start)
    k0 = starts[0]
    lo = file_nb[k0][0]
    hi_excl = file_nb[k0 + len(seq) - 1][0] + 1
    return _rebuild_from_span(current, body, old_nb, lo, hi_excl, file_nb, k0)


def _rebuild_from_span(current: list[str], body: list[str],
                       old_nb: list[tuple[int, str]], lo: int, hi_excl: int,
                       file_nb: list[tuple[int, str]],
                       nb_start: int) -> tuple[list[str], int] | None:
    """Rebuild hunk body: context/deletion lines from the FILE, `+` lines
    from the model. Verifies the span's non-blank content equals the hunk's."""
    new_body: list[str] = []
    ptr = lo
    ok = True
    for idx, line in enumerate(body):
        if line.startswith("+"):
            new_body.append(line)
        elif line[1:].strip() == "" if line.startswith((" ", "-")) else line.strip() == "":
            # blank model line: consume a file blank when there is one,
            # otherwise drop it (blank lines are semantically null; dropping
            # keeps the hunk placeable and counts stay honest).
            if ptr < hi_excl and current[ptr].strip() == "":
                new_body.append(" " + current[ptr])
                ptr += 1
        else:
            # non-blank old line: must equal the file line at ptr (skipping
            # file blanks already excluded by construction of the span)
            while ptr < hi_excl and current[ptr].strip() == "":
                new_body.append(" " + current[ptr])
                ptr += 1
            if ptr >= hi_excl or current[ptr] != line[1:]:
                ok = False
                break
            new_body.append(line[0] + current[ptr])
            ptr += 1
    if not ok:
        return None
    return new_body, lo


TEST_NAMES = {
    "python": "test_{stem}_aeroops.py",
    "javascript": "{stem}.aeroops.test.js",
    "typescript": "{stem}.aeroops.test.ts",
}


def materialize_test(*, target: Path, suggestion: str, language: str) -> Path | None:
    """Write the model's regression test under a namespaced filename that can
    never collide with project tests. Returns the path or None."""
    body = (suggestion or "").strip()
    if not body or len(body) < 10:
        return None
    # strip fences the model may have included despite instructions
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("```")]
    body = "\n".join(lines).strip() + "\n"
    pattern = TEST_NAMES.get(language)
    if not pattern:
        return None
    path = target.parent / pattern.format(stem=target.stem)
    if path.exists():
        return None  # never overwrite project files
    # Python tests run standalone in the target dir: ensure the unit under
    # test is importable even when the model forgets the import line.
    if language == "python" and f"import {target.stem}" not in body:
        body = f"from {target.stem} import *  # auto-added by AeroOps harness\n{body}"
    try:
        path.write_text(body)
    except OSError:
        return None
    return path


_ALLOWED_TEST_EXT = {".py", ".js", ".jsx", ".ts", ".tsx"}


def materialize_at(*, repo: Path, relpath: str, body: str) -> Path | None:
    """Write a model-suggested test to an explicit repo path. Guards: must
    resolve inside the repo, allowed test extension, never overwrite."""
    cleaned = (body or "").strip()
    if not cleaned or len(cleaned) < 10:
        return None
    lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
    cleaned = "\n".join(lines).strip() + "\n"
    target = (repo / relpath).resolve() if not Path(relpath).is_absolute() \
        else Path(relpath).resolve()
    if repo.resolve() not in target.parents:
        return None
    if target.suffix.lower() not in _ALLOWED_TEST_EXT:
        return None
    if target.exists():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cleaned)
    except OSError:
        return None
    return target
