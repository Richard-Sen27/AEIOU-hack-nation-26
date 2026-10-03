def assert_error(r, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code


ASSET = {
    "kind": "asset",
    "payload": {
        "asset_type": "registry",
        "name": "STXBP1 natural history registry",
        "url": "https://example.org/registry",
        "disease_ids": ["MONDO:0013276"],
    },
}
PHENO = {
    "kind": "phenotype_profile",
    "payload": {
        "disease_id": "MONDO:0013276",
        "phenotype_ids": ["HP:0001250", "HP:0001263"],
        "excluded_phenotype_ids": ["HP:0011968"],
        "age_range": "1-5",
    },
}
EDGE = {
    "kind": "candidate_edge",
    "payload": {
        "source_id": "MONDO:0013276",
        "target_id": "HGNC:11444",
        "relation": "caused_by_variant_in",
        "source_id_ref": "PMID:12345678",
        "quote": "De novo STXBP1 variants cause early infantile epileptic encephalopathy.",
    },
}
