"""Load SQL: the HPO term table and the per-disease change diff recorded before the truncate.
The load needs a database, so these tests check the staging frames and the generated SQL; the
SQL itself is not executed here."""

import json

import polars as pl

from pipeline import load


def test_load_stages_hpo_terms_as_json_arrays():
    df = pl.DataFrame(
        {
            "id": ["HP:1"],
            "label": ["Seizure"],
            "synonyms": [["Seizures", "Épilepsie"]],
            "parents": [["HP:2"]],
            "ic": [None],
        },
        schema={
            "id": pl.String,
            "label": pl.String,
            "synonyms": pl.List(pl.String),
            "parents": pl.List(pl.String),
            "ic": pl.Float64,
        },
    )
    out = load.hpo_terms_frame(df)
    assert json.loads(out["synonyms"][0]) == ["Seizures", "Épilepsie"]
    assert json.loads(out["parents"][0]) == ["HP:2"]
    assert load.hpo_terms_frame(None).height == 0
    assert "hpo_terms" in load.STAGING_DDL
    assert "INSERT INTO hpo_terms" in load.PROMOTE
    assert "to_regclass('public.hpo_terms')" in load.PROMOTE


def test_graph_changes_diff_runs_before_the_truncate_and_carries_its_guards():
    sql = load.PROMOTE
    begin, diff = sql.index("BEGIN;"), sql.index("INSERT INTO graph_changes")
    assert begin < diff < sql.index("TRUNCATE evidence, edges")
    assert sql.index("TRUNCATE evidence") < sql.index("COMMIT;")
    assert "to_regclass('public.graph_changes')" in sql  # missing table: skipped
    assert "\\if :has_changes_table" in sql and "\\if :has_previous" in sql  # first load: none
    assert "JOIN prev_diseases" in sql  # only diseases of the previous version
    for rel in load.CHANGE_RELATIONS:
        assert f"'{rel}'" in sql
    assert "'now_recruiting'" in sql and "attrs->>'status' = 'RECRUITING'" in sql
    assert f"rank <= {load.CHANGES_PER_DISEASE}" in sql
    assert "extract(year FROM now())::int - 1" in sql  # papers: this year and last year
    assert f"LIMIT {load.CHANGES_KEEP_VERSIONS}" in sql
    assert "ARRAY['trial', 'patient_org', 'grant', 'paper']" in sql
