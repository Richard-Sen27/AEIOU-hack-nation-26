"""Load SQL: the HPO term table.
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
