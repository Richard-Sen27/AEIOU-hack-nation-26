import pytest

from pipeline import config, load
from pipeline.llm import LLMSettings
from pipeline.sources.clinicaltrials import TrialsSettings
from pipeline.sources.patient_orgs import BrightDataSettings
from pipeline.sources.pubmed import PubMedSettings
from pipeline.sources.reporter import ReporterSettings

CASES = [
    (config.Settings, "RESEARCHER_MIN_LINKS=7", "researcher_min_links", 7),
    (LLMSettings, "PIPELINE_LLM_MAX_CALLS=7", "max_calls", 7),
    (PubMedSettings, "PUBMED_MAX_PER_GENE=7", "max_per_gene", 7),
    (ReporterSettings, "REPORTER_MAX_PER_TERM=7", "max_per_term", 7),
    (TrialsSettings, "CLINICALTRIALS_MAX_PER_GENE=7", "max_per_gene", 7),
    (BrightDataSettings, "BRIGHTDATA_SERP_ZONE=zone7", "serp_zone", "zone7"),
]


@pytest.mark.parametrize("cls,line,field,expected", CASES)
def test_env_file_reaches_every_settings_class(tmp_path, monkeypatch, cls, line, field, expected):
    env = tmp_path / ".env"
    env.write_text(line + "\n")
    monkeypatch.delenv(line.split("=")[0], raising=False)
    # Each class reads pipeline.paths.ENV_FILE; check that is configured, then load it.
    assert cls.model_config.get("env_file") is not None
    assert getattr(cls(_env_file=env), field) == expected


def test_settings_classes_point_at_pipeline_env_file():
    from pipeline.paths import ENV_FILE

    for cls, *_ in CASES:
        assert cls.model_config["env_file"] == ENV_FILE


def test_psql_path_resolution(monkeypatch):
    monkeypatch.setattr(config.settings, "psql_bin", "/custom/psql")
    assert config.psql_path() == "/custom/psql"
    monkeypatch.setattr(config.settings, "psql_bin", None)
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/psql")
    assert config.psql_path() == "/usr/bin/psql"
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="PSQL_BIN"):
        config.psql_path()


def test_pipeline_commit_prefers_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_COMMIT", "abc123")
    assert load.pipeline_commit() == "abc123"
    monkeypatch.delenv("PIPELINE_COMMIT")
    assert len(load.pipeline_commit()) in (0, 40)
