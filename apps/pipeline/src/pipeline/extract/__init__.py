"""Stage 3: LLM extraction from abstracts and patient-organization pages."""

from __future__ import annotations


async def run(scope=None) -> None:
    from pipeline.contracts import load_scope
    from pipeline.extract import abstracts, patient_orgs
    from pipeline.llm import LLMRun

    scope = scope or load_scope()
    llm_run = LLMRun.start()
    await abstracts.run(scope, llm_run)
    await patient_orgs.run(scope, llm_run)
    llm_run.log_summary()
