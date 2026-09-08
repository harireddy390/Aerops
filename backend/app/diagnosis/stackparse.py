"""Stack-trace forensics: turn raw crash text into structured evidence.

Understands CPython tracebacks and Node/V8 stacks. Everything downstream
(fingerprinting, specific rules, AI context) builds on this — never on raw text.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

PY_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+), in (\S+)', re.M)
PY_EXC = re.compile(r"^(\w[\w.]*?(?:Error|Exception|Exit|Interrupt|Warning))\s*:\s*(.*)$", re.M)
NODE_FRAME = re.compile(r"^\s*at (?:(.+?) \()?(.+?):(\d+):(\d+)\)?\s*$", re.M)
NODE_EXC = re.compile(r"^(\w*Error)\s*:\s*(.*)$", re.M)


@dataclass
class Frame:
    file: str
    line: int
    func: str


@dataclass
class CrashEvidence:
    language: str = "unknown"  # python | node | unknown
    exc_type: str = ""
    exc_msg: str = ""
    frames: list[Frame] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def location(self) -> str:
        """Innermost frame first: where it actually blew up."""
        if not self.frames:
            return ""
        f = self.frames[-1]
        short = f.file.split("/")[-1].split("\\")[-1]
        return f"{short}:{f.line}" + (f" ({f.func})" if f.func not in ("<module>", "<anonymous>") else "")


def parse(text: str) -> CrashEvidence:
    text = text or ""
    ev = CrashEvidence()
    py_frames = [Frame(m.group(1), int(m.group(2)), m.group(3)) for m in PY_FRAME.finditer(text)]
    if py_frames:
        ev.language = "python"
        ev.frames = py_frames[-8:]  # keep the blast radius small
        m = None
        for m in PY_EXC.finditer(text):
            pass
        if m:
            ev.exc_type, ev.exc_msg = m.group(1).strip(), m.group(2).strip()[:500]
        ev.fingerprint = fingerprint(ev.exc_type, ev.frames[-1] if ev.frames else None)
        return ev
    node_frames = []
    for m in NODE_FRAME.finditer(text):
        func, path, line = m.group(1) or "<anonymous>", m.group(2), int(m.group(3))
        if "node:internal" in path:  # runtime internals are noise for fingerprinting
            continue
        node_frames.append(Frame(path, line, func))
    if node_frames or NODE_EXC.search(text):
        ev.language = "node"
        ev.frames = node_frames[-8:]
        m = NODE_EXC.search(text)
        if m:
            ev.exc_type, ev.exc_msg = m.group(1).strip(), m.group(2).strip()[:500]
        if not ev.exc_type and "Cannot read properties of undefined" in text:
            ev.exc_type = "TypeError"
            ev.exc_msg = "Cannot read properties of undefined"
        ev.fingerprint = fingerprint(ev.exc_type, ev.frames[-1] if ev.frames else None)
    return ev


def fingerprint(exc_type: str, frame: Frame | None) -> str:
    if not exc_type and frame is None:
        return ""
    loc = f"{frame.file.split('/')[-1].split(chr(92))[-1]}:{frame.line}" if frame else ""
    return hashlib.sha1(f"{exc_type}|{loc}".encode()).hexdigest()[:12]
