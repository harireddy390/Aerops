"""Browser-stack translation: turn live Vite/React crash references into
local repo hints the remediation pipeline can resolve.

Published apps crash with references like:
  https://my-app.lovable.app/assets/index-a9f2c1.js:10:245
  http://localhost:5173/src/App.tsx?t=1726:15:10
  at render (src/components/Cart.tsx:42:9)

Bundled assets (assets/index-*.js) carry no source mapping, so the best local
hint is the basename; dev-server and component stacks carry the real
`src/...` path, which maps directly into `workspace_frontend`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# any http(s) URL, or a bare source path with a JS/TS/CSS-like extension.
# Line/col numbers ride as trailing :line[:col] (Vite appends ?t= busters,
# stripped first). One alternation so matches stay in stack order.
REF = re.compile(
    r"(?P<url>https?://[^\s()\"']+)"
    r"|(?P<path>(?<![\w/.:-])[A-Za-z0-9_./\\-]+\.(?:tsx|ts|jsx|js|mjs|cjs|css|vue|svelte)"
    r"(?:\?[^\s()\"':]*)?(?::\d+)?(?::\d+)?)")
TAIL_NUMS = re.compile(r"^(.*?)(?::(\d+))?(?::(\d+))?$")
SRC_MARKER = re.compile(r"src/[^?\s()\"':]+")


@dataclass
class ClientHint:
    file_hint: str  # repo-resolvable hint, e.g. src/App.tsx or index-a9f2.js
    line: int
    column: int = 0


def strip_noise(ref: str) -> str:
    """Drop query strings, hashes and surrounding punctuation from a URL/path."""
    ref = (ref or "").strip().strip("<>\"'()")
    ref = ref.split("?")[0].split("#")[0]
    return ref


def _peel_numbers(ref: str) -> tuple[str, int, int]:
    """Split trailing :line[:col] off a cleaned URL/path (ports preserved)."""
    m = TAIL_NUMS.match(ref)
    if not m:
        return ref, 0, 0
    try:
        return m.group(1), int(m.group(2) or 0), int(m.group(3) or 0)
    except ValueError:
        return ref, 0, 0


def to_repo_hint(raw: str) -> str:
    """Map one raw stack file reference to a repo-relative hint.

    Prefers the `src/...` suffix (dev servers, sourcemaps, component stacks);
    falls back to the basename for hashed production bundles.
    """
    ref = strip_noise(raw)
    if not ref:
        return ""
    ref, _, _ = _peel_numbers(ref)
    if not ref:
        return ""
    m = SRC_MARKER.search(ref.replace("\\", "/"))
    if m:
        return m.group(0)
    # plain relative path already (src/App.tsx, ./src/App.tsx)
    cleaned = ref.replace("\\", "/")
    if "/" in cleaned and not cleaned.startswith(("http://", "https://")):
        return cleaned.lstrip("./")
    # absolute URL or bare filename -> basename (hashed bundle or page)
    return cleaned.split("/")[-1]


def hints_from_stack(stack_trace: str, *, file_path: str = "",
                     line: int = 0, column: int = 0) -> list[ClientHint]:
    """Ordered candidate hints: explicit SDK fields first, then stack order.

    The SDK already extracts file/line/col from the throw site, so those win;
    every additional stack reference follows as a fallback for the resolver.
    """
    hints: list[ClientHint] = []
    if (file_path or "").strip():
        hints.append(ClientHint(file_hint=to_repo_hint(file_path),
                                line=max(0, int(line or 0)),
                                column=max(0, int(column or 0))))
    seen = {h.file_hint for h in hints if h.file_hint}
    for m in REF.finditer(stack_trace or ""):
        raw = m.group("url") or m.group("path") or ""
        ref = strip_noise(raw)
        if not ref:
            continue
        ref, ln, col = _peel_numbers(ref)
        hint = to_repo_hint(ref)
        if not hint or hint in seen:
            continue
        # skip runtime/vendor noise; keep app code (incl. hashed bundles)
        low = hint.lower()
        if "node_modules" in low or low.startswith("node:"):
            continue
        seen.add(hint)
        hints.append(ClientHint(file_hint=hint, line=ln, column=col))
        if len(hints) >= 8:
            break
    return [h for h in hints if h.file_hint]


def primary_hint(stack_trace: str, *, file_path: str = "",
                 line: int = 0, column: int = 0) -> ClientHint:
    """The single best hint: explicit fields, else first src/ hit, else first."""
    hints = hints_from_stack(stack_trace, file_path=file_path, line=line, column=column)
    if not hints:
        return ClientHint(file_hint="", line=0, column=0)
    for h in hints:
        if h.file_hint.startswith("src/"):
            return h
    return hints[0]
