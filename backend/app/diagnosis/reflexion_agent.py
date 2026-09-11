"""Reflexion engine: verification failures become better second attempts.

Loop (max 2 retries): the failed patch + exact harness output go back to the
model with orders to fix BOTH the original crash and the verification failure.
Exhaustion => caller escalates the incident to a human. Never raises.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.diagnosis.code_diagnosis_agent import CodeFixProposal, parse_proposal
from app.remediation.test_harness import VerifyReport

log = get_logger("reflexion")

MAX_REFLEXIONS = 2

REFINE_SUFFIX = (
    "\n\nYour previous patch FAILED verification with this exact output:\n"
    "{failure}\nThe patch you tried:\n---\n{attempted}\n---\n"
    "Revise search_block and replacement_block so BOTH the original crash and "
    "this verification failure are resolved. Keep the edit surgical. "
    "If it cannot be done safely, return an empty replacement_block.")

GOLDEN_REFINE_SUFFIX = (
    "\n\nYour previous diff FAILED verification with this exact output:\n"
    "{failure}\nThe diff you tried:\n---\n{attempted}\n---\n"
    "Revise the unified diff (and test) so BOTH the original crash and this "
    "verification failure are resolved. Keep the edit surgical: exact context "
    "lines, minimal hunk. CRITICAL: your test must assert EXACTLY what your "
    "patched code returns for the same inputs — a test disagreeing with its "
    "own patch is the most common failure. Output the full <<<DIAGNOSIS>>> / "
    "<<<PATCH>>> / <<<TEST_SUITE_SUGGESTION>>> schema again. If it cannot be "
    "done safely, leave PATCH empty.")


async def _refine(error: str, context_block: str, attempted: CodeFixProposal,
                  failure: str) -> tuple[CodeFixProposal | None, str]:
    from app.diagnosis import code_diagnosis_agent as agent
    prompt = (agent.build_prompt(file_path="same file", language="auto",
                                 error=error, context_block=context_block)
              + REFINE_SUFFIX.format(failure=failure[:1500],
                                     attempted=(attempted.search_block + "\n>>>\n"
                                                + attempted.replacement_block)[:1500]))
    for _ in range(1):  # one shot per round; outer loop bounds the retries
        try:
            raw = await agent._ask_openai(prompt)
            if raw and (p := agent.parse_proposal(raw)):
                return p, "openai"
        except Exception:
            pass
        try:
            raw = await agent._ask_ollama(prompt)
            if raw and (p := agent.parse_proposal(raw)):
                return p, "ollama"
        except Exception:
            pass
    return None, ""


async def propose_with_reflexion(propose_fn, *, error: str, context_block: str,
                                 try_patch) -> tuple[CodeFixProposal | None, str, str]:
    """Drive propose -> try_patch cycles.

    try_patch(proposal) -> (ok: bool, failure_text: str).
    Returns (proposal, provider, outcome) where outcome is one of
    "verified" | "escalated". try_patch performs apply+verify+rollback itself.
    """
    proposal, provider = await propose_fn()
    if not proposal:
        return None, "", "escalated"
    for round_no in range(MAX_REFLEXIONS + 1):
        ok, failure = await try_patch(proposal)
        if ok:
            return proposal, provider, "verified"
        log.info(f"reflexion round {round_no}: verification failed, refining")
        if round_no >= MAX_REFLEXIONS:
            break
        refined, provider2 = await _refine(error, context_block, proposal, failure)
        if not refined:
            break
        proposal, provider = refined, provider2
    return proposal, provider, "escalated"


async def propose_golden_with_reflexion(propose_fn, *, error: str,
                                        context_block: str,
                                        try_patch):
    """Same loop for GoldenProposal diffs. try_patch(proposal) ->
    (ok, failure_text); returns (proposal, provider, outcome)."""
    from app.diagnosis import code_diagnosis_agent as agent
    proposal, provider = await propose_fn()
    if not proposal:
        return None, "", "escalated"
    for round_no in range(MAX_REFLEXIONS + 1):
        ok, failure = await try_patch(proposal)
        if ok:
            return proposal, provider, "verified"
        log.info(f"golden reflexion round {round_no}: failed, refining")
        if round_no >= MAX_REFLEXIONS:
            break
        refined, provider2 = await _refine_golden(error, context_block, proposal, failure)
        if not refined:
            break
        proposal, provider = refined, provider2
    return proposal, provider, "escalated"


async def _refine_golden(error: str, context_block: str, attempted,
                         failure: str):
    from app.diagnosis import code_diagnosis_agent as agent
    prompt = (agent.build_prompt(file_path="same file", language="auto",
                                 error=error, context_block=context_block)
              + GOLDEN_REFINE_SUFFIX.format(
                  failure=failure[:1500],
                  attempted=attempted.diff_text[:1500]))
    for _ in range(1):
        try:
            raw = await agent._ask_openai_golden(prompt)
            if raw and (p := agent.parse_golden(raw)):
                return p, "openai"
        except Exception:
            pass
        try:
            raw = await agent._ask_ollama_golden(prompt)
            if raw and (p := agent.parse_golden(raw)):
                return p, "ollama"
        except Exception:
            pass
    return None, ""


async def propose_multifile_with_reflexion(propose_fn, *, error: str,
                                           context_block: str,
                                           service_name: str, incident_id: int,
                                           runtime_error: str, crash_locus: str,
                                           stack: str, slices: str,
                                           runtime_env: str, test_command: str,
                                           try_patch):
    """v2 loop for MultiProposal diffs: initial attempt + up to 2 refinements
    fed with harness stderr. Returns (proposal, provider, outcome)."""
    from app.diagnosis import code_diagnosis_agent as agent
    proposal, provider = await propose_fn()
    if not proposal:
        return None, "", "escalated"
    for round_no in range(MAX_REFLEXIONS + 1):
        ok, failure = await try_patch(proposal)
        if ok:
            return proposal, provider, "verified"
        log.info(f"multifile reflexion round {round_no}: failed, refining")
        if round_no >= MAX_REFLEXIONS:
            break
        refined, provider2 = await agent.refine_multifile(
            service_name=service_name, incident_id=incident_id,
            runtime_error=runtime_error, crash_locus=crash_locus,
            stack_trace=stack, code_slices=slices,
            runtime_env=runtime_env, test_command=test_command,
            previous_diff="\n".join(proposal.patches), failure=failure)
        if not refined:
            break
        proposal, provider = refined, provider2
    return proposal, provider, "escalated"
