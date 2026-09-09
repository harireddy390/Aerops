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
