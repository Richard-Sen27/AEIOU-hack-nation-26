from pathlib import Path

import pytest

from pipeline import contracts, llm
from pipeline.contracts import Scope
from pipeline.extract import abstracts as x_abstracts
from pipeline.extract import patient_orgs as x_orgs
from pipeline.sources import clinicaltrials, patient_orgs, pubmed, reporter

try:  # the OpenAI platform agent's mock server, when the backend ships it
    from backend.devtools.mock_openai.fixtures import (  # noqa: F401
        _mock_openai_server,
        mock_openai,
        mock_openai_env,
    )
except ImportError:  # pragma: no cover
    pass

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    """Point every module of this half of the pipeline at a temporary data/ tree."""
    raw, norm, ext, cache = (tmp_path / d for d in ("raw", "normalized", "extracted", "cache"))
    for mod in (contracts, pubmed, clinicaltrials, reporter, patient_orgs):
        for name, value in (("RAW", raw), ("NORMALIZED", norm), ("EXTRACTED", ext)):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, value)
    for mod in (x_abstracts, x_orgs):
        monkeypatch.setattr(mod, "NORMALIZED", norm)
        monkeypatch.setattr(mod, "EXTRACTED", ext)
    monkeypatch.setattr(llm, "LLM_CACHE", cache / "llm")
    return {"raw": raw, "normalized": norm, "extracted": ext, "cache": cache}


@pytest.fixture
def scope() -> Scope:
    return Scope(
        data_version="test",
        genes=[
            {"hgnc_id": "HGNC:11444", "symbol": "STXBP1", "aliases": ["MUNC18-1"], "seed": True},
            {"hgnc_id": "HGNC:10585", "symbol": "SCN1A", "aliases": [], "seed": True},
            {"hgnc_id": "HGNC:10596", "symbol": "SCN8A", "aliases": [], "seed": True},
            {"hgnc_id": "HGNC:18865", "symbol": "KCNT1", "aliases": [], "seed": True},
        ],
        diseases=[
            {
                "mondo_id": "MONDO:0100135",
                "label": "Dravet syndrome",
                "synonyms": ["Dravet", "severe myoclonic epilepsy of infancy", "DS"],
                "seed": True,
            },
            {
                "mondo_id": "MONDO:0012812",
                "label": "developmental and epileptic encephalopathy, 4",
                "synonyms": [
                    "DEE4",
                    "STXBP1-related encephalopathy",
                    "STXBP1 early infantile epileptic encephalopathy",
                ],
                "seed": True,
            },
            {
                "mondo_id": "MONDO:0013801",
                "label": "developmental and epileptic encephalopathy, 13",
                "synonyms": ["SCN8A epilepsy", "SCN8A encephalopathy"],
                "seed": True,
            },
            {
                "mondo_id": "MONDO:0013989",
                "label": "developmental and epileptic encephalopathy, 14",
                "synonyms": ["KCNT1-related epilepsy"],
                "seed": True,
            },
        ],
        phenotypes=[
            {"hpo_id": "HP:0001250", "label": "Seizure", "synonyms": ["Seizures"]},
            {"hpo_id": "HP:0001249", "label": "Intellectual disability", "synonyms": []},
        ],
    )
