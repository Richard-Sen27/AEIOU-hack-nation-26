import pytest

from pipeline.extract.common import (
    ScopeMatcher,
    disease_query_terms,
    institution_id,
    institution_name,
    normalize_orcid,
    person_name_key,
    quote_in_text,
    researcher_id,
    scrub_contacts,
)

ABSTRACT = (
    "Pathogenic variants in STXBP1 cause a severe\n  developmental and epileptic "
    "encephalopathy. Haploinsufficiency—rather than dominant‑negative effects—is "
    "the main mechanism; patients’ seizures start early."
)


@pytest.mark.parametrize(
    "quote",
    [
        "Pathogenic variants in STXBP1 cause a severe developmental and epileptic encephalopathy.",
        "Pathogenic variants in STXBP1 cause a severe   developmental",  # whitespace differs
        "Haploinsufficiency-rather than dominant-negative effects-is the main mechanism",  # dashes
        "patients' seizures start early.",  # typographic apostrophe
        "  the main mechanism  ",
    ],
)
def test_quote_accepted(quote):
    assert quote_in_text(quote, ABSTRACT)


@pytest.mark.parametrize(
    "quote",
    [
        "STXBP1 variants cause a severe developmental and epileptic encephalopathy.",  # paraphrase
        "pathogenic variants in STXBP1 cause",  # case differs
        "Pathogenic variants in STXBP1 ... encephalopathy",  # ellipsis
        "Haploinsufficiency is the main mechanism",  # stitched spans
        "",
        None,
    ],
)
def test_quote_rejected(quote):
    assert not quote_in_text(quote, ABSTRACT)


def test_quote_unicode_compatibility_forms():
    assert quote_in_text("ﬁrst-in-class", "a first-in-class drug")  # NFKC ligature
    assert quote_in_text("Na channel", "Na channel")  # thin space is whitespace


def test_disease_matching(scope):
    m = ScopeMatcher(scope)
    assert [x.node_id for x in m.diseases_in("Dravet Syndrome")] == ["MONDO:0100135"]
    assert m.diseases_in("Dravet Syndrome")[0].method == "exact"
    hit = m.diseases_in("Seizure in Participants With Dravet Syndrome (DS)")
    assert [x.node_id for x in hit] == ["MONDO:0100135"]
    stx = m.diseases_in("STXBP1 Encephalopathy With Epilepsy")
    assert [(x.node_id, x.method) for x in stx] == [("MONDO:0012812", "gene_tokens")]
    assert m.diseases_in("KCNT1-Related Epilepsy")[0].node_id == "MONDO:0013989"


@pytest.mark.parametrize(
    "text",
    [
        "Epilepsy",
        "Developmental and Epileptic Encephalopathy",
        "SCN8A benign familial infantile epilepsy",  # tokens present but not as the phrase
        "Down syndrome DS",  # short acronyms never match inside text
        "STXBP1",
        "",
    ],
)
def test_disease_matching_rejects_unconfident(scope, text):
    assert ScopeMatcher(scope).diseases_in(text) == []


def test_ambiguous_terms_are_dropped(scope):
    scope.diseases[1]["synonyms"].append("Dravet syndrome")
    m = ScopeMatcher(scope)
    assert m.diseases_in("Dravet syndrome") == []


def test_query_terms_skip_numbered_labels(scope):
    terms = disease_query_terms(scope, scope.diseases[1])
    assert "developmental and epileptic encephalopathy, 4" not in terms
    assert "STXBP1-related encephalopathy" in terms
    assert "DS" not in disease_query_terms(scope, scope.diseases[0])


def test_researcher_keying():
    assert person_name_key("Helbig", "Ingo H") == ("ingo helbig", False)
    assert person_name_key("Helbig", "Ingo") == ("ingo helbig", False)
    assert person_name_key("Müller", "Jürgen") == ("jurgen muller", False)
    assert person_name_key("Smith", "J")[1] is True
    key, _ = person_name_key("Helbig", "Ingo H")
    assert researcher_id(key) == researcher_id("ingo helbig")
    assert researcher_id(key).startswith("RES:")
    assert researcher_id(key, "0000-0002-1825-0097") == "ORCID:0000-0002-1825-0097"
    assert normalize_orcid("https://orcid.org/0000-0002-1825-009x") == "0000-0002-1825-009X"
    assert normalize_orcid("000000021825009X") == "0000-0002-1825-009X"
    assert normalize_orcid("n/a") is None


@pytest.mark.parametrize(
    "aff,expected",
    [
        (
            "Division of Neurology, Children's Hospital of Philadelphia, Philadelphia, PA, USA.",
            "Children's Hospital of Philadelphia",
        ),
        (
            "Neuroscience Program, University of Pennsylvania, Philadelphia, PA 19104, USA.",
            "University of Pennsylvania",
        ),
        (
            "Dept. of Neurology, Second Affiliated Hospital, Zhejiang University, Hangzhou, China",
            "Second Affiliated Hospital, Zhejiang University",
        ),
        ("Department of Pediatrics, Second Affiliated Hospital, Hangzhou, China", None),
        ("Some Lab, Somewhere. Electronic address: someone@example.org.", None),
        ("", None),
    ],
)
def test_institution_name(aff, expected):
    assert institution_name(aff) == expected


def test_institution_ids_ignore_accents_and_case():
    assert institution_id("Hospital Sant Joan de Déu") == institution_id(
        "HOSPITAL SANT JOAN DE DEU"
    )


def test_scrub_contacts():
    text = "Write to a.b@example.org or call +1 (555) 010-0199. Electronic address: x@y.org."
    out = scrub_contacts(text)
    assert "@" not in out and "555" not in out
