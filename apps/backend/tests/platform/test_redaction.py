"""Synthetic reports and messages (all names, dates, addresses and ids are invented)."""

import pytest

from backend.privacy.redaction import get_redactor, redact

CASES = [
    (
        "My daughter Emma Thompson is 2, diagnosed with STXBP1 last month. Lots of seizures, "
        "not walking yet, no problems with eating. Call me at (415) 555-0132 or "
        "emma.mom@gmail.com.",
        ["Emma Thompson", "555-0132", "emma.mom@gmail.com"],
        ["STXBP1", "is 2,", "seizures", "no problems with eating"],
    ),
    (
        "GENETIC TEST REPORT\nPatient: Johnson, Michael\nDOB: 03/14/2019\nMRN: 00482913\n"
        "Address: 742 Evergreen Terrace, Springfield, IL 62704\nReport date: 2024-05-02\n"
        "Result: Heterozygous pathogenic variant in SCN1A NM_001165963.4:c.1216C>T "
        "p.(Arg406*). Consistent with Dravet syndrome (MONDO:0100135). "
        "Ordering physician: Dr. Sarah Klein.",
        ["Johnson", "Michael", "03/14/2019", "00482913", "742 Evergreen", "62704", "Sarah Klein"],
        [
            "SCN1A",
            "NM_001165963.4:c.1216C>T",
            "p.(Arg406*)",
            "Dravet syndrome",
            "MONDO:0100135",
            "2024-05-02",
            "DOB:",
            "MRN:",
        ],
    ),
    (
        "Befund\nPatientin: Anna Gruber\nGeb.: 12.04.2020\nSVNR: 1234 120420\n"
        "Adresse: Mariahilfer Straße 45/3, 1060 Wien\nTel.: +43 664 1234567\n"
        "Befunddatum: 03.02.2025\nNachweis einer heterozygoten Variante im Gen CDKL5 c.215T>C. "
        "West-Syndrom, Lennox-Gastaut-Syndrom differenzialdiagnostisch. Kind ist 4 Jahre alt, "
        "lebt in Österreich.",
        ["Anna Gruber", "12.04.2020", "1234 120420", "Mariahilfer", "1060 Wien", "664 1234567"],
        [
            "CDKL5",
            "c.215T>C",
            "West-Syndrom",
            "Lennox-Gastaut-Syndrom",
            "03.02.2025",
            "4 Jahre alt",
            "Österreich",
        ],
    ),
    (
        "Dear Dr. Patel, I am writing about my son Lucas (born on March 3, 2021). He was "
        "diagnosed with Ohtahara syndrome and later West syndrome. Insurance ID: XKJ-449-2381. "
        "We live at 18 Oak Lane, Boston, MA 02118, United States.",
        ["Patel", "Lucas", "March 3, 2021", "XKJ-449-2381", "18 Oak Lane", "02118"],
        ["Ohtahara syndrome", "West syndrome", "United States"],
    ),
    (
        "Sehr geehrte Frau Dr. Huber, unser Sohn Maximilian Bauer, geboren am 5. Jänner 2019, "
        "hat eine Rett-Syndrom-ähnliche Symptomatik. MECP2 negativ, FOXG1 c.460dup "
        "p.(Glu154Glyfs*301). Versicherungsnummer: 4455 050119. Fallnummer: 2024/10234.",
        ["Huber", "Maximilian", "Bauer", "5. Jänner 2019", "4455 050119", "2024/10234"],
        ["Rett-Syndrom", "MECP2", "FOXG1", "c.460dup", "p.(Glu154Glyfs*301)"],
    ),
    (
        "Hi, I'm Olivia Martinez. My son Noah was born 07/22/2018 and has Lennox-Gastaut "
        "syndrome due to a de novo SCN2A variant (c.5645G>A). We are in Canada. "
        "My number is +1 604 555 0199.",
        ["Olivia Martinez", "Noah", "07/22/2018", "604 555 0199"],
        ["Lennox-Gastaut", "SCN2A", "c.5645G>A", "Canada"],
    ),
    (
        "CLINICAL LETTER\nName: Sophie Laurent\nDate of birth: 1 February 2017\n"
        "Patient ID: PT-883021\nHospital number: 55-102-993\n"
        "Diagnosis: Angelman syndrome (UBE3A deletion). Phenotype: HP:0001250 seizures, "
        "HP:0001263 global developmental delay. Seen on 14.06.2024 at age 7 years.",
        ["Sophie Laurent", "1 February 2017", "PT-883021"],
        ["Angelman syndrome", "UBE3A", "HP:0001250", "HP:0001263", "14.06.2024", "7 years"],
    ),
    (
        "Laborbefund\nPatient: Lukas Hofer\nGeburtsdatum: 23.09.2016\nLabornummer: L-2024-55821\n"
        "Einsender: Dr. med. Petra Wimmer, Spitalgasse 23, 1090 Wien\n"
        "Ergebnis: Pathogene Variante in KCNQ2 NM_172107.4:c.881C>T, vereinbar mit "
        "Ohtahara-Syndrom (ORPHA:1934).",
        [
            "Lukas Hofer",
            "23.09.2016",
            "L-2024-55821",
            "Petra Wimmer",
            "Spitalgasse 23",
            "1090 Wien",
        ],
        ["KCNQ2", "NM_172107.4:c.881C>T", "Ohtahara-Syndrom", "ORPHA:1934"],
    ),
    (
        "From: grace.okafor@outlook.com\nMy name is Grace Okafor, mother of Daniel (DOB "
        "2019-11-30). Member ID: WX9928341. He has Dravet syndrome and we are looking for a "
        "registry. Our address is 221 Baker Street, London.",
        [
            "grace.okafor@outlook.com",
            "Grace Okafor",
            "Daniel",
            "2019-11-30",
            "WX9928341",
            "221 Baker Street",
        ],
        ["Dravet syndrome", "registry"],
    ),
    (
        "Mrs. Hannah Schmidt called about her 5 year old twins. Medical record number: "
        "MR-77120. Both carry PCDH19 c.1091dup and were evaluated for Rett syndrome; MECP2 "
        "testing was negative (reported 2023-08-14). They live in Germany.",
        ["Hannah Schmidt", "MR-77120"],
        ["5 year old", "PCDH19", "c.1091dup", "Rett syndrome", "MECP2", "2023-08-14", "Germany"],
    ),
    (
        "Patient: Liam O'Connor, d.o.b. 15/05/2020, NHS number 943 476 5919. "
        "Whole exome: GRIN2B p.(Gly689Ser), likely pathogenic. Differential includes "
        "West syndrome and Doose syndrome (MONDO:0011873).",
        ["Liam", "O'Connor", "15/05/2020", "943 476 5919"],
        ["GRIN2B", "p.(Gly689Ser)", "West syndrome", "Doose syndrome", "MONDO:0011873"],
    ),
]


@pytest.fixture(scope="module")
def redactor():
    return get_redactor()


@pytest.mark.parametrize("text,pii,keep", CASES)
def test_redacts_pii_and_keeps_medical_content(redactor, text, pii, keep):
    result = redactor.redact(text)
    for value in pii:
        assert value not in result.text, f"PII left: {value!r} in {result.text!r}"
    for term in keep:
        assert term in result.text, f"medical term lost: {term!r} in {result.text!r}"


def test_spans_map_back_to_original():
    text = "Patient: Johnson, Michael\nDOB: 03/14/2019\nVariant SCN1A c.1216C>T."
    result = redact(text)
    assert result.redacted
    for span in result.spans:
        assert result.text[span.redacted_start : span.redacted_end] == span.placeholder
        assert text[span.start : span.end].strip()
    start = result.text.index("SCN1A")
    o_start, o_end = result.to_original(start, start + len("SCN1A c.1216C>T"))
    assert text[o_start:o_end] == "SCN1A c.1216C>T"
    dob = next(s for s in result.spans if s.entity_type == "DATE_OF_BIRTH")
    assert text[dob.start : dob.end] == "03/14/2019"
    assert result.to_original(dob.redacted_start, dob.redacted_end) == (dob.start, dob.end)


def test_allow_terms():
    text = "We saw Dr. Wu and talked about Kleefstra; my son Kai Lindqvist is 3."
    result = redact(text, allow_terms=["Kai Lindqvist"])
    assert "Kai Lindqvist" in result.text
    assert "Dr. Wu" in result.text


def test_typed_placeholders_and_empty():
    result = redact("Email jane.roe@example.org or call 212-555-0147.")
    assert result.text == "Email <EMAIL> or call <PHONE>."
    assert result.entity_counts() == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1}
    assert redact("").text == "" and not redact("   ").redacted


def test_test_dates_survive_but_birth_dates_do_not():
    text = "Sample collected 2024-03-01, reported 12.03.2024. Born 01.02.2020."
    result = redact(text)
    assert "2024-03-01" in result.text and "12.03.2024" in result.text
    assert "01.02.2020" not in result.text
