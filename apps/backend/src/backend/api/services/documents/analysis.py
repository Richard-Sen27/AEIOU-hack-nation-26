"""Classification, structured extraction and grounding of findings.

The model only ever sees redacted page text. Every finding it returns is checked in code: the
snippet must occur on the stated page and must support the extracted value; others are dropped.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.llm import LLMClient
from backend.schemas.enums import (
    DocType,
    FindingType,
    Relation,
    VariantClassification,
    Zygosity,
)

MAX_MODEL_CHARS = 120_000
CLASSIFY_CHARS = 8_000
MAX_SNIPPET_CHARS = 600
MAX_FINDINGS = 60

PREAMBLE = (
    "You read a document uploaded by a user of a rare-disease atlas. Personal data was removed "
    "before you see it: placeholders such as <PERSON>, <DATE_OF_BIRTH>, <ADDRESS> and <ID> mark "
    "removed text. Never guess or reconstruct removed data. The text is split into "
    '<page n="..."> blocks.'
)


class BiologyRelation(StrEnum):
    caused_by_variant_in = Relation.caused_by_variant_in.value
    acts_via = Relation.acts_via.value
    participates_in = Relation.participates_in.value
    has_phenotype = Relation.has_phenotype.value
    same_gene_same_mechanism = Relation.same_gene_same_mechanism.value
    same_gene_different_mechanism = Relation.same_gene_different_mechanism.value
    shared_pathway = Relation.shared_pathway.value
    similar_symptoms = Relation.similar_symptoms.value


# ---- model output schemas ---------------------------------------------------------------------


class DocClassification(BaseModel):
    doc_type: DocType = Field(
        description="genetic_report (lab genetic test result), clinical_letter (doctor's letter, "
        "discharge summary, clinic note), research_paper (scientific article or preprint), "
        "registry_document (patient registry, natural history or clinical study document)."
    )


_SNIPPET = (
    "Exact text copied character for character from that page (one to three lines) that "
    "supports this item."
)


class VariantItem(BaseModel):
    gene: str = Field(description="Gene symbol exactly as written, e.g. STXBP1.")
    hgvs: str | None = Field(description="HGVS notation exactly as written, e.g. c.1631G>A.")
    zygosity: Zygosity | None
    classification: VariantClassification | None
    test_date: str | None = Field(description="Date of the test or report as YYYY-MM-DD.")
    page: int = Field(description="Page number the snippet is on.")
    snippet: str = Field(description=_SNIPPET + " Must contain the gene and the variant.")


class GeneticReportExtraction(BaseModel):
    variants: list[VariantItem]


class ConditionItem(BaseModel):
    label: str = Field(description="Diagnosis or disease name as written.")
    page: int
    snippet: str = Field(description=_SNIPPET)


class SymptomItem(BaseModel):
    label: str = Field(description="Symptom or clinical finding as written.")
    excluded: bool = Field(description="True when the text says the symptom is absent.")
    page: int
    snippet: str = Field(description=_SNIPPET)


class ClinicalLetterExtraction(BaseModel):
    diagnoses: list[ConditionItem]
    symptoms: list[SymptomItem]


class RegistryExtraction(BaseModel):
    diseases: list[ConditionItem]


class RelationItem(BaseModel):
    subject: str = Field(description="Gene, disease, pathway, mechanism or phenotype name.")
    relation: BiologyRelation
    object: str = Field(description="Gene, disease, pathway, mechanism or phenotype name.")
    page: int
    quote: str = Field(description="Exact sentence copied from that page that states it.")


class ResearchPaperExtraction(BaseModel):
    relations: list[RelationItem]


INSTRUCTIONS: dict[DocType, tuple[type[BaseModel], str]] = {
    DocType.genetic_report: (
        GeneticReportExtraction,
        "Extract every reported genetic variant: gene, HGVS variant, zygosity, classification "
        "(pathogenic, likely_pathogenic, uncertain_significance for VUS, likely_benign, benign) "
        "and the test or report date. Use null when a field is not stated. Do not interpret.",
    ),
    DocType.clinical_letter: (
        ClinicalLetterExtraction,
        "Extract diagnoses (diseases) and symptoms or clinical findings. Mark symptoms the text "
        "says are absent as excluded. Do not add anything that is not written.",
    ),
    DocType.registry_document: (
        RegistryExtraction,
        "Extract the diseases this registry or study document is about.",
    ),
    DocType.research_paper: (
        ResearchPaperExtraction,
        "Extract relations between genes, diseases, pathways, mechanisms and phenotypes that the "
        "paper states as findings. Use only the given relation types; at most 15 relations.",
    ),
}


# ---- helpers ----------------------------------------------------------------------------------


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("‐", "-").replace("‑", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def pages_for_model(pages: list[str], limit: int = MAX_MODEL_CHARS) -> str:
    out, used = [], 0
    for i, page in enumerate(pages, start=1):
        block = f'<page n="{i}">\n{page.strip()}\n</page>'
        if used + len(block) > limit:
            remaining = limit - used
            if remaining > 200:
                out.append(block[: remaining - 8] + "\n</page>")
            break
        out.append(block)
        used += len(block)
    return "\n".join(out)


def snippet_on_page(pages: list[str], page: int, snippet: str) -> bool:
    if not (1 <= page <= len(pages)):
        return False
    s = norm(snippet)
    return len(s) >= 3 and len(snippet) <= MAX_SNIPPET_CHARS and s in norm(pages[page - 1])


_STOP = {"of", "the", "and", "with", "type", "due", "to", "in", "a", "an", "or", "for", "not"}


def label_supported(label: str, snippet: str) -> bool:
    """Every significant word of `label` (or its stem) appears in the snippet."""
    s = norm(snippet)
    if norm(label) in s:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]+", norm(label)) if t not in _STOP]
    if not tokens:
        return False
    for t in tokens:
        stem = t if len(t) <= 4 else t[: max(4, len(t) - 3)]
        if stem not in s:
            return False
    return True


def gene_supported(gene: str, snippet: str) -> bool:
    gene = gene.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{0,14}", gene):
        return False
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(gene)}(?![A-Za-z0-9])", snippet, re.I) is not None
    )


def hgvs_supported(hgvs: str, snippet: str, page_text: str) -> bool:
    compact = re.sub(r"\s+", "", hgvs)
    snip = re.sub(r"\s+", "", snippet)
    if compact in snip:
        return True
    # "NM_003165.6:c.1631G>A" may be written as "NM_003165.6(STXBP1):c.1631G>A"
    if ":" in compact:
        prefix, change = compact.rsplit(":", 1)
        transcript = re.sub(r"\(.*\)$", "", prefix)
        return change in snip and transcript in re.sub(r"\s+", "", page_text)
    return False


_CLASS_PATTERNS: dict[VariantClassification, re.Pattern] = {
    VariantClassification.likely_pathogenic: re.compile(r"likely[\s_-]+pathogenic", re.I),
    VariantClassification.pathogenic: re.compile(
        r"(?<!likely )(?<!likely_)(?<!non-)(?<!non )\bpathogenic\b", re.I
    ),
    VariantClassification.uncertain_significance: re.compile(
        r"uncertain[\s_-]+significance|unknown[\s_-]+significance|\bVUS\b", re.I
    ),
    VariantClassification.likely_benign: re.compile(r"likely[\s_-]+benign", re.I),
    VariantClassification.benign: re.compile(r"(?<!likely )(?<!likely_)\bbenign\b", re.I),
}

_ZYGOSITY_PATTERNS: dict[Zygosity, re.Pattern] = {
    Zygosity.heterozygous: re.compile(r"(?<!compound )\bhet(?:erozygous|\.)?(?![a-z])", re.I),
    Zygosity.homozygous: re.compile(r"\bhom(?:ozygous|\.)?(?![a-z])", re.I),
    Zygosity.hemizygous: re.compile(r"\bhemizygous\b", re.I),
    Zygosity.compound_heterozygous: re.compile(r"compound[\s-]+het", re.I),
    Zygosity.mosaic: re.compile(r"\bmosaic", re.I),
    Zygosity.unknown: re.compile(r"."),
}

_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def date_supported(value: str, page_text: str) -> date | None:
    try:
        d = date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    month = _MONTHS[d.month - 1]
    forms = {
        d.isoformat(),
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day}.{d.month}.{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year}",
        f"{d.day}/{d.month}/{d.year}",
        f"{d.month}/{d.day}/{d.year}",
        f"{d.day} {month} {d.year}",
        f"{d.day} {month[:3]} {d.year}",
        f"{month} {d.day}, {d.year}",
        f"{month[:3]} {d.day}, {d.year}",
        f"{month} {d.day} {d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
    }
    page = norm(page_text)
    return d if any(f in page for f in forms) else None


# ---- drafts -----------------------------------------------------------------------------------


@dataclass
class FindingDraft:
    type: FindingType
    value: str
    page: int
    snippet: str
    payload: dict[str, Any] = field(default_factory=dict)
    normalized_id: str | None = None
    lookup: str | None = None  # label to resolve to a graph id


async def classify(llm: LLMClient, pages: list[str]) -> DocType:
    out = await llm.structured(
        DocClassification,
        instructions=PREAMBLE + " Classify the document.",
        input=pages_for_model(pages, CLASSIFY_CHARS),
        kind="small",
    )
    return out.doc_type


async def extract(llm: LLMClient, doc_type: DocType, pages: list[str]) -> list[FindingDraft]:
    schema, task = INSTRUCTIONS[doc_type]
    out = await llm.structured(
        schema,
        instructions=f"{PREAMBLE} {task} For every item give the page number and a snippet "
        "copied exactly from that page.",
        input=pages_for_model(pages),
        kind="small",
    )
    return ground(doc_type, out, pages)[:MAX_FINDINGS]


def ground(doc_type: DocType, out: BaseModel, pages: list[str]) -> list[FindingDraft]:
    """Keep only items whose snippet is on the stated page and supports the value."""
    drafts: list[FindingDraft] = []
    if isinstance(out, GeneticReportExtraction):
        for v in out.variants:
            drafts.extend(_ground_variant(v, pages))
    elif isinstance(out, ClinicalLetterExtraction):
        for c in out.diagnoses:
            drafts.extend(_ground_label(FindingType.disease, c.label, c.page, c.snippet, pages))
        for s in out.symptoms:
            for d in _ground_label(FindingType.phenotype, s.label, s.page, s.snippet, pages):
                d.payload["excluded"] = s.excluded
                drafts.append(d)
    elif isinstance(out, RegistryExtraction):
        for c in out.diseases:
            drafts.extend(_ground_label(FindingType.disease, c.label, c.page, c.snippet, pages))
    elif isinstance(out, ResearchPaperExtraction):
        for r in out.relations:
            if not snippet_on_page(pages, r.page, r.quote):
                continue
            if not (label_supported(r.subject, r.quote) and label_supported(r.object, r.quote)):
                continue
            drafts.append(
                FindingDraft(
                    type=FindingType.candidate_edge,
                    value=f"{r.subject.strip()} {r.relation.value} {r.object.strip()}",
                    page=r.page,
                    snippet=r.quote.strip(),
                    payload={
                        "subject": r.subject.strip(),
                        "object": r.object.strip(),
                        "relation": r.relation.value,
                        "quote": r.quote.strip(),
                    },
                )
            )
    return _dedupe(drafts)


def _ground_label(
    ftype: FindingType, label: str, page: int, snippet: str, pages: list[str]
) -> list[FindingDraft]:
    label = label.strip()
    if not label or len(label) > 200:
        return []
    if not snippet_on_page(pages, page, snippet) or not label_supported(label, snippet):
        return []
    return [
        FindingDraft(
            type=ftype,
            value=label,
            page=page,
            snippet=snippet.strip(),
            payload={"label": label},
            lookup=label,
        )
    ]


def _ground_variant(v: VariantItem, pages: list[str]) -> list[FindingDraft]:
    if not snippet_on_page(pages, v.page, v.snippet) or not gene_supported(v.gene, v.snippet):
        return []
    page_text = pages[v.page - 1]
    gene = v.gene.strip()
    snippet = v.snippet.strip()
    gene_draft = FindingDraft(
        type=FindingType.gene,
        value=gene,
        page=v.page,
        snippet=snippet,
        payload={"symbol": gene},
        lookup=gene,
    )
    if not v.hgvs or not hgvs_supported(v.hgvs, v.snippet, page_text):
        return [gene_draft]
    classification = v.classification
    if classification and not _CLASS_PATTERNS[classification].search(page_text):
        classification = None
    zygosity = v.zygosity
    if zygosity and not _ZYGOSITY_PATTERNS[zygosity].search(page_text):
        zygosity = None
    test_date = date_supported(v.test_date, page_text) if v.test_date else None
    hgvs = v.hgvs.strip()
    variant = FindingDraft(
        type=FindingType.variant,
        value=f"{gene} {hgvs}",
        page=v.page,
        snippet=snippet,
        payload={
            "gene": gene,
            "gene_id": None,
            "hgvs": hgvs,
            "zygosity": zygosity.value if zygosity else None,
            "classification": classification.value if classification else None,
            "test_date": test_date.isoformat() if test_date else None,
            "clinvar_id": None,
        },
        lookup=hgvs,
    )
    return [gene_draft, variant]


def _dedupe(drafts: list[FindingDraft]) -> list[FindingDraft]:
    seen: set[tuple] = set()
    out = []
    for d in drafts:
        key = (d.type, norm(d.value), d.payload.get("excluded"))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out
