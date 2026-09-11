"""Code diagnosis agent: small-model-friendly proposer of SURGICAL patches.

Strategy for weak models (Ollama local / free tiers): never ask for file
rewrites. Ask for one exact search/replace block plus a verification command
from an allowlist. Output is pure JSON, defensively parsed, Pydantic-validated.
"""
from __future__ import annotations

import json
import re

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("code-agent")


class CodeFixProposal(BaseModel):
    root_cause: str = Field(min_length=1, max_length=500)
    search_block: str = Field(min_length=1, max_length=4000)
    replacement_block: str = Field(min_length=1, max_length=4000)
    verification_command: str = Field(default="node --check", max_length=200)


class GoldenProposal(BaseModel):
    """Unified-diff remediation with a shipped regression test."""
    root_cause: str = Field(min_length=1, max_length=500)
    failure_line: str = Field(default="", max_length=200)
    strategy: str = Field(default="", max_length=500)
    diff_text: str = Field(min_length=1, max_length=6000)
    test_suggestion: str = Field(default="", max_length=4000)


class RegressionTest(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    language: str = Field(default="python", max_length=20)
    body: str = Field(min_length=1, max_length=4000)


class MultiProposal(BaseModel):
    """Full-stack remediation: diagnosis + one diff per file + one test."""
    root_cause: str = Field(min_length=1, max_length=500)
    upstream_origin: str = Field(default="", max_length=200)
    crash_site: str = Field(default="", max_length=200)
    strategy: str = Field(default="", max_length=800)
    patches: list[str] = Field(default_factory=list, max_length=5)
    test: RegressionTest | None = None


GOLDEN_SYSTEM_PROMPT = """You are AeroOps Senior Site Reliability & Remediation Core.
Your objective is to diagnose an uncaught runtime exception and produce a minimal, non-breaking, surgical patch.

### INPUT CONTRACT:
- [INCIDENT_CONTEXT]: service metadata provided by the operator harness.
- [STACK_TRACE]: the exact error class, message and failing line.
- [TARGET_FILE_CONTEXT]: source lines around the failure, with line numbers.
- [WORKSPACE_STATE]: sibling files, test setup, dependencies.

### CRITICAL RULES:
1. MINIMAL IMPACT: fix only the bug and its direct side effects. No refactors, no reformatting, no style changes.
2. NULL/UNDEFINED SAFETY: guard nil/undefined dereferences, missing keys, type mismatches.
3. PRESERVE CONTRACTS: do not change exported signatures, module exports, or route paths.
4. DIFF HYGIENE: file context lines look like `   9 |     return x`. The `9 | ` prefix is a LINE NUMBER, not file content — NEVER include it in search_block, replacement_block, or the diff. Diffs contain raw file lines only, with ` `, `-`, `+` markers and correct @@ counts.
4. DETERMINISTIC OUTPUT: output MUST strictly follow the schema below. No conversational filler, no markdown fences.

### OUTPUT SCHEMA (adhere strictly):
<<<DIAGNOSIS>>>
Root Cause: <single sentence on why it crashed>
Failure Line: <Filename:LineNumber>
Strategy: <the defensive check applied>
<<<END_DIAGNOSIS>>>

<<<PATCH>>>
--- a/{target}
+++ b/{target}
@@ -<start>,<count> +<start>,<count> @@
<unified diff that `git apply` accepts: context lines start with a space>
<<<END_PATCH>>>

<<<TEST_SUITE_SUGGESTION>>>
<A minimal runnable test proving the fix: pytest-style `def test_...` for Python
(starting with `from <target_stem> import *`), or a plain `node --check`-clean
JS snippet exercising the fixed path — self-contained, or require('./<file>')
explicitly. No fixtures, no network, stdlib/assert only.>
<<<END_TEST_SUITE_SUGGESTION>>>

If no safe surgical fix exists, output the DIAGNOSIS block and leave PATCH empty."""


SYSTEM_PROMPT = """You are a surgical code-repair bot. You fix ONE runtime crash with the SMALLEST possible edit.

RULES (violating any rule fails the task):
1. Output PURE JSON only. No markdown fences, no prose, no explanation outside the JSON.
2. "search_block" must be 1-8 EXACT lines copied verbatim from the provided file context.
3. "replacement_block" is the fixed version of exactly those lines. Same indentation style.
4. Prefer guards over rewrites: check for null/undefined, missing keys, empty state BEFORE use.
5. Never rename variables, never reformat unrelated lines, never add dependencies.
6. "verification_command" must be ONE of: node --check <file> | npx tsc --noEmit | npm run build | npm test | python -m py_compile <file>.
   Always name the file for node --check / py_compile (a bare checker with no file hangs).
7. If you cannot fix it with a small guarded edit, set "replacement_block" to "" (empty = escalate to human).

JSON schema (exact keys):
{"root_cause": "one sentence: why it crashed",
 "search_block": "exact lines to remove",
 "replacement_block": "exact replacement lines, or empty to escalate",
 "verification_command": "one allowlisted command"}"""


def build_prompt(*, file_path: str, language: str, error: str,
                 context_block: str) -> str:
    return (f"File: {file_path} ({language})\n"
            f"Crash: {error[:500]}\n\n"
            f"File context (line numbers shown, fix must come from THESE lines):\n"
            f"{context_block[:3000]}")


def build_golden_prompt(*, service_name: str, error_message: str,
                        stack_trace: str, file_path: str,
                        file_content: str) -> str:
    """Golden prompt: full incident contract for surgical diff remediation."""
    return (f"You are AeroOps Senior Site Reliability & Remediation Core.\n"
            f"Your objective is to diagnose an uncaught runtime exception and produce a minimal, non-breaking, surgical patch.\n\n"
            f"### INPUT CONTRACT:\n"
            f"- Service: {service_name}\n"
            f"- Error: {error_message[:800]}\n\n"
            f"### STACK_TRACE:\n{stack_trace[:1500]}\n\n"
            f"### TARGET_FILE: {file_path}\n"
            f"```source\n{file_content[:3000]}\n```\n"
            f"CRITICAL RULES:\n"
            f"MINIMAL IMPACT: Do not refactor unrelated code. Fix only the failure.\n"
            f"PRESERVE CONTRACTS: Do not modify exported function signatures.\n"
            f"OUTPUT FORMAT: Output valid Unified Diff inside <<>> delimiters that git apply can run directly. No conversation.\n\n"
            f"OUTPUT SCHEMA:\n"
            f"<<<DIAGNOSIS>>>\nRoot Cause:\nFailure Line: Filename:LineNumber\nStrategy:\n<<<END_DIAGNOSIS>>>\n\n"
            f"<<<PATCH>>>\n--- a/{file_path}\n+++ b/{file_path}\n@@ ... @@\n<<<END_PATCH>>>\n\n"
            f"<<<TEST_SUITE_SUGGESTION>>>\n<A minimal runnable test proving the fix>\n<<<END_TEST_SUITE_SUGGESTION>>>")


def _section(text: str, name: str) -> str:
    m = re.search(rf"<<<{name}>>>(.*?)<<<END_{name}>>>", text, re.S)
    return m.group(1).strip() if m else ""


def _kv(block: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}\s*:\s*(.+)$", block, re.M)
    return m.group(1).strip() if m else ""


def parse_golden(raw: str) -> GoldenProposal | None:
    """Extract the three delimited blocks; validate as a GoldenProposal."""
    if not raw:
        return None
    text = re.sub(r"```(?:diff|json|python|javascript|typescript)?", "", raw)
    diag, patch, test = (_section(text, "DIAGNOSIS"), _section(text, "PATCH"),
                         _section(text, "TEST_SUITE_SUGGESTION"))
    if not diag or not patch:
        return None
    try:
        proposal = GoldenProposal(
            root_cause=_kv(diag, "Root Cause") or diag.splitlines()[0][:500],
            failure_line=_kv(diag, "Failure Line"),
            strategy=_kv(diag, "Strategy"),
            diff_text=patch,
            test_suggestion=test[:4000])
    except Exception:
        return None
    if "--- " not in proposal.diff_text or "@@" not in proposal.diff_text:
        return None
    return proposal


async def _ask_ollama(prompt: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_sec) as client:
            r = await client.post(f"{settings.ollama_base_url}/api/generate", json={
                "model": settings.ollama_model,
                "system": SYSTEM_PROMPT,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "seed": 7, "num_predict": 800},
            })
            r.raise_for_status()
            return r.json().get("response", "")
    except Exception as exc:
        log.info(f"code agent ollama failed: {type(exc).__name__}")
        return None


async def _ask_openai(prompt: str) -> str | None:
    if not settings.openai_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_sec) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.openai_model, "temperature": 0.1,
                      "max_tokens": 800,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                   {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        log.info(f"code agent openai failed: {type(exc).__name__}")
        return None


def parse_proposal(raw: str) -> CodeFixProposal | None:
    """Defensive parse: strip fences/prose, extract first JSON object, validate."""
    if not raw:
        return None
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start = text.find("{")
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    obj = {k: v for k, v in obj.items()
           if k in ("root_cause", "search_block", "replacement_block", "verification_command")}
    try:
        proposal = CodeFixProposal(**obj)
    except Exception:
        return None
    if not proposal.replacement_block.strip():
        return None  # model escalated to human
    return proposal


async def propose_fix(*, file_path: str, language: str, error: str,
                      context_block: str, attempts: int = 3) -> tuple[CodeFixProposal | None, str]:
    """Try OpenAI first, then Ollama, up to `attempts` rounds. Small local
    models are flaky per-call; retries are cheap, patches stay gated.
    Returns (proposal, provider). Never raises."""
    prompt = build_prompt(file_path=file_path, language=language, error=error,
                          context_block=context_block)
    for _ in range(max(1, attempts)):
        try:
            raw = await _ask_openai(prompt)
            if raw and (proposal := parse_proposal(raw)):
                return proposal, f"openai:{settings.openai_model}"
        except Exception:
            pass
        try:
            raw = await _ask_ollama(prompt)
            if raw and (proposal := parse_proposal(raw)):
                return proposal, f"ollama:{settings.ollama_model}"
        except Exception:
            pass
    return None, ""


async def propose_golden(*, service_name: str, error_message: str,
                         stack_trace: str, file_path: str,
                         file_content: str,
                         attempts: int = 2) -> tuple[GoldenProposal | None, str]:
    """Golden path: unified-diff proposal + regression test suggestion.
    Temperature ladder (0.1 -> 0.4 -> 0.7) so retries sample differently
    instead of repeating the same failure. Never raises."""
    prompt = build_golden_prompt(service_name=service_name,
                                 error_message=error_message,
                                 stack_trace=stack_trace, file_path=file_path,
                                 file_content=file_content)
    last_raw = ""

    async def attempt(temp: float) -> tuple[GoldenProposal | None, str, str]:
        nonlocal last_raw
        try:
            raw = await _ask_openai_golden(prompt, temp)
            last_raw = raw or last_raw
            if raw and (proposal := parse_golden(raw)):
                return proposal, f"openai:{settings.openai_model}", raw
        except Exception:
            pass
        try:
            raw = await _ask_ollama_golden(prompt, temp)
            last_raw = raw or last_raw
            if raw and (proposal := parse_golden(raw)):
                return proposal, f"ollama:{settings.ollama_model}", raw
        except Exception:
            pass
        return None, "", last_raw

    for round_no, temp in enumerate([0.1, 0.4, 0.7][:max(1, attempts) + 1]):
        proposal, provider, _ = await attempt(temp)
        if proposal:
            return proposal, provider
    propose_golden.last_raw = last_raw  # introspection for escalation records
    return None, ""


async def refine_multifile(*, service_name: str, incident_id: int,
                           runtime_error: str, crash_locus: str,
                           stack_trace: str, code_slices: str,
                           runtime_env: str, test_command: str,
                           previous_diff: str,
                           failure: str) -> tuple[MultiProposal | None, str]:
    """One reflexion round: previous diff + harness stderr fed back in."""
    prompt = (build_v2_prompt(
        service_name=service_name, incident_id=incident_id,
        runtime_error=runtime_error, crash_locus=crash_locus,
        stack_trace=stack_trace, code_slices=code_slices,
        runtime_env=runtime_env, test_command=test_command)
        + f"\n\nYour previous diff FAILED verification with this exact output:\n"
          f"{failure[:1500]}\nThe diff you tried:\n---\n{previous_diff[:1500]}\n---\n"
          f"Revise the unified diff (and test) so BOTH the original crash and "
          f"this verification failure are resolved. Keep it surgical. If it "
          f"cannot be done safely, leave PATCHES empty.")
    for temp in (0.4, 0.7):
        raw, provider = await _ask_v2(prompt, temp)
        if raw and (proposal := parse_multifile(raw)):
            return proposal, provider
    return None, ""


async def _ask_ollama_golden(prompt: str, temperature: float = 0.1,
                             system: str | None = None) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_code_timeout_sec) as client:
            r = await client.post(f"{settings.ollama_base_url}/api/generate", json={
                "model": settings.ollama_model,
                "system": system or GOLDEN_SYSTEM_PROMPT,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "seed": 7, "num_predict": 800},
            })
            r.raise_for_status()
            return r.json().get("response", "")
    except Exception as exc:
        log.info(f"golden ollama failed: {type(exc).__name__}")
        return None


async def _ask_openai_golden(prompt: str, temperature: float = 0.1,
                             system: str | None = None) -> str | None:
    if not settings.openai_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_sec) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.openai_model, "temperature": temperature,
                      "max_tokens": 1200,
                      "messages": [{"role": "system", "content": system or GOLDEN_SYSTEM_PROMPT},
                                   {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        log.info(f"golden openai failed: {type(exc).__name__}")
        return None


V2_SYSTEM_PROMPT = """You are AeroOps Principal Systems Reliability Agent.
Your mandate is to diagnose, root-cause, and generate surgical patches for uncaught exceptions across full-stack applications (Frontend, Backend, and Shared Schemas).

### INPUT CONTEXT CONTRACT:
- [INCIDENT_ID], [RUNTIME_ERROR], [CRASH_LOCUS], [STACK_TRACE],
  [RELEVANT_CODE_SLICES], [ENVIRONMENT & HARNESS] arrive in the user message.

### INVESTIGATION METHODOLOGY:
1. TRACE DATA FLOW: check if the value arrived corrupted from upstream helpers, hooks, or backend responses.
2. DEFENSIVE INTEGRITY: defend the crash site and enforce correct upstream contracts.
3. MINIMAL BLAST RADIUS: zero cosmetic refactors. Preserve public contracts and signatures.
4. SYNTHESIZE REGRESSION TEST: produce a minimal test case preventing future regressions.

### OUTPUT FORMAT (strict delimiters, JSON is NOT used here):
<<<DIAGNOSIS>>>
Root Cause: <precise explanation>
Upstream Origin: <File:Line or "N/A - Direct Call">
Crash Site: <File:Line>
Remediation Strategy: <explanation>
<<<END_DIAGNOSIS>>>

<<<PATCHES>>>
--- a/{one primary file, then optional further ---/+++ file blocks}
+++ b/{same}
@@ ... @@
<unified diff chunk(s); raw file lines only, never line-number prefixes>
<<<END_PATCHES>>>

<<<REGRESSION_TEST>>>
File: <repo-relative path for the test, e.g. test_billing_aeroops.py>
Language: <typescript|javascript|python>
```test
<minimal test asserting safe error handling; pytest-style def test_... for
python (start with `from <module> import *`), self-contained snippet for JS>
<<<END_REGRESSION_TEST>>>

Rules: pure delimited output only, no fences around the whole reply (fences
inside the test block are tolerated and stripped). If no safe fix exists,
emit DIAGNOSIS and leave PATCHES empty."""


def build_v2_prompt(*, incident_id: int, runtime_error: str, crash_locus: str,
                    stack_trace: str, code_slices: str, runtime_env: str,
                    test_command: str, service_name: str = "") -> str:
    return (f"### INPUT CONTEXT CONTRACT:\n"
            f"- [SERVICE]: {service_name}\n"
            f"- [INCIDENT_ID]: {incident_id}\n"
            f"- [RUNTIME_ERROR]: {runtime_error[:800]}\n"
            f"- [CRASH_LOCUS]: {crash_locus[:200]}\n"
            f"- [STACK_TRACE]:\n{stack_trace[:1500]}\n"
            f"- [RELEVANT_CODE_SLICES]:\n{code_slices[:5000]}\n"
            f"- [ENVIRONMENT & HARNESS]:\nRuntime: {runtime_env}\n"
            f"Test Harness: {test_command or 'auto-detect'}\n")


def _v2_section(text: str, name: str) -> str:
    m = re.search(rf"<<<{name}>>>(.*?)<<<END_{name}>>>", text, re.S)
    return m.group(1).strip() if m else ""


def parse_multifile(raw: str) -> MultiProposal | None:
    """Parse the v2 delimited contract into a MultiProposal."""
    if not raw:
        return None
    text = raw.strip()
    diag = _v2_section(text, "DIAGNOSIS")
    patches = _v2_section(text, "PATCHES")
    test = _v2_section(text, "REGRESSION_TEST")
    if not diag or not patches or "--- " not in patches or "@@" not in patches:
        return None
    try:
        proposal = MultiProposal(
            root_cause=_kv(diag, "Root Cause") or diag.splitlines()[0][:500],
            upstream_origin=_kv(diag, "Upstream Origin"),
            crash_site=_kv(diag, "Crash Site"),
            strategy=_kv(diag, "Remediation Strategy"),
            patches=[patches],
            test=_parse_v2_test(test),
        )
    except Exception:
        return None
    return proposal


def _parse_v2_test(block: str) -> RegressionTest | None:
    if not block:
        return None
    path = ""
    language = "python"
    for line in block.splitlines():
        low = line.strip().lower()
        if low.startswith("file:"):
            path = line.split(":", 1)[1].strip().strip("`").strip()
        elif low.startswith("language:"):
            language = line.split(":", 1)[1].strip().strip("`").lower()
    m = re.search(r"```test(.*?)```", block, re.S)
    body = (m.group(1) if m else block).strip()
    body = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("```")).strip()
    if not path or not body:
        return None
    if language not in ("python", "javascript", "typescript"):
        language = "python"
    return RegressionTest(path=path[:300], language=language, body=body[:4000])


async def _ask_v2(prompt: str, temperature: float) -> tuple[str, str] | tuple[None, None]:
    try:
        raw = await _ask_openai_golden(prompt, temperature, V2_SYSTEM_PROMPT)
        if raw:
            return raw, f"openai:{settings.openai_model}"
    except Exception:
        pass
    try:
        raw = await _ask_ollama_golden(prompt, temperature, V2_SYSTEM_PROMPT)
        if raw:
            return raw, f"ollama:{settings.ollama_model}"
    except Exception:
        pass
    return None, None


async def propose_multifile(*, service_name: str, incident_id: int,
                            runtime_error: str, crash_locus: str,
                            stack_trace: str, code_slices: str,
                            runtime_env: str, test_command: str,
                            attempts: int = 2) -> tuple[MultiProposal | None, str]:
    """v2 proposer with temperature ladder. Never raises."""
    base = (f"You are AeroOps Principal Systems Reliability Agent.\n"
            f"Output ONLY the delimited schema, no fences around the reply.\n\n")
    prompt = base + build_v2_prompt(
        service_name=service_name, incident_id=incident_id,
        runtime_error=runtime_error, crash_locus=crash_locus,
        stack_trace=stack_trace, code_slices=code_slices,
        runtime_env=runtime_env, test_command=test_command)
    last_raw = ""
    for temp in [0.1, 0.4, 0.7][:max(1, attempts) + 1]:
        raw, provider = await _ask_v2(prompt, temp)
        last_raw = raw or last_raw
        if raw and (proposal := parse_multifile(raw)):
            return proposal, provider
    propose_multifile.last_raw = last_raw
    return None, ""
