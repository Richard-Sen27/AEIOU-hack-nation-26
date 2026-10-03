"""Helpers shared by the literature/community connectors and Stage 3: text normalization,
quote verification, stable ids for people and institutions, and scope term matching."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from pipeline.contracts import Scope

# Typographic variants that NFKC leaves alone but are the same character to a reader.
_UNICODE_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "­": None,  # soft hyphen
        "​": None,  # zero-width space
        "‌": None,
        "‍": None,
        "﻿": None,
    }
)
_WS = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Unicode (NFKC + typographic quotes/dashes) and whitespace normalization; case is kept."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_UNICODE_FOLD)
    return _WS.sub(" ", text).strip()


def quote_in_text(quote: str | None, text: str | None) -> bool:
    """True iff the normalized quote occurs verbatim in the normalized text. Nothing fuzzier."""
    q = normalize_text(quote)
    return bool(q) and q in normalize_text(text)


def fold(text: str | None) -> str:
    """Lowercase, accent-free, punctuation-free form used for matching names and terms."""
    text = unicodedata.normalize("NFKD", normalize_text(text))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return _WS.sub(" ", text).strip()


def short_hash(*parts: str, n: int = 12) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:n]


def slugify(text: str) -> str:
    return fold(text).replace(" ", "-")[:60].strip("-")


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_ELECTRONIC = re.compile(r"\s*Electronic address:\s*", re.I)
_PHONE = re.compile(
    r"(?:\+|\b00)\d[\d\s().-]{7,}\d|\(\d{3}\)\s*\d{3}[\s.-]\d{4}|\b\d{3}[.-]\d{3}[.-]\d{4}\b"
)


def scrub_contacts(text: str | None) -> str:
    """Remove e-mail addresses and phone numbers (compliance: no personal contact data)."""
    if not text:
        return ""
    text = _ELECTRONIC.sub(" ", text)
    text = _EMAIL.sub("", text)
    return _PHONE.sub("", text)


# ---------------------------------------------------------------------------------------------
# People and institutions


def person_name_key(last: str | None, first: str | None) -> tuple[str, bool]:
    """Conservative name key "<first given name> <last name>" (folded) and whether it is weak.

    Only the first given name is used (middle names and initials vary between sources); a key
    whose given name is a bare initial is flagged weak because it collides easily.
    """
    last_f = fold(last)
    given = fold(first).split()
    first_tok = given[0] if given else ""
    weak = len(first_tok) <= 1
    return f"{first_tok} {last_f}".strip(), weak


def researcher_id(name_key: str, orcid: str | None = None) -> str:
    if orcid:
        return f"ORCID:{orcid}"
    return f"RES:{short_hash('researcher', name_key)}"


def doctor_id(name_key: str) -> str:
    return f"DOC:{short_hash('doctor', name_key)}"


_ORCID = re.compile(r"(\d{4}-?\d{4}-?\d{4}-?\d{3}[\dXx])")


def normalize_orcid(raw: str | None) -> str | None:
    m = _ORCID.search(raw or "")
    if not m:
        return None
    digits = m.group(1).replace("-", "").upper()
    return "-".join(digits[i : i + 4] for i in range(0, 16, 4))


_INST_WORDS = re.compile(
    r"\b(universit\w*|hospital\w*|h[oô]pital\w*|ospedale|klinik\w*|clinic\w*|institut\w*|"
    r"istituto|instituto|college|school of medicine|medical cent(er|re)|cent(er|re)|"
    r"foundation|fondazione|fundaci[oó]n|academy|inserm|cnrs|nih|"
    r"children's|kinderspital|ziekenhuis|umc|irccs|health system|healthcare|laborator\w*)\b",
    re.I,
)
_SUBUNIT = re.compile(
    r"^(dep(t|artment)\.?|division|program(me)?|laborator(y|ies)|lab|unit|section|service|"
    r"faculty|graduate|group|team|chair|core|neuroscience program|research program)\b",
    re.I,
)
_STRONG = re.compile(
    r"universit|hospital|h[oô]pital|ospedale|institut|istituto|college|klinik", re.I
)
_NEEDS_PARENT = re.compile(
    r"^(the )?((first|second|third|fourth|fifth|sixth|seventh|eighth|\w+) affiliated|affiliated|"
    r"(college|school|faculty|institute) of (medicine|life sciences|pharmacy|basic medical"
    r"|medical|public health|biological|biomedical))",
    re.I,
)
_STOP_INST = {"center", "centre", "institute", "university", "hospital", "laboratory", "school"}


def institution_name(affiliation: str | None) -> str | None:
    """Pick the organisation from a free-text affiliation, or None when it doesn't parse cleanly.

    "Division of Neurology, Children's Hospital of Philadelphia, Philadelphia, PA, USA" ->
    "Children's Hospital of Philadelphia". Sub-units ("Department of ...") are skipped.
    """
    text = scrub_contacts(affiliation).strip().rstrip(".")
    if not text:
        return None
    text = text.split(";")[0]
    parts = [p.strip(" .") for p in text.split(",") if p.strip(" .")]
    candidates = [p for p in parts if _INST_WORDS.search(p) and not _SUBUNIT.match(p)]
    if not candidates:
        return None
    strong = [p for p in candidates if _STRONG.search(p)]
    name = (strong or candidates)[0]
    # "Second Affiliated Hospital" or "College of Life Sciences" only identify an institution
    # together with their parent university.
    if _NEEDS_PARENT.match(name) and not re.search(r"universit", name, re.I):
        parents = [p for p in candidates if p != name and re.search(r"universit", p, re.I)]
        if not parents:
            return None
        name = f"{name}, {parents[0]}"
    if len(name) < 6 or len(name) > 120 or fold(name) in _STOP_INST or re.search(r"\d{3,}", name):
        return None
    return name


def institution_id(name: str) -> str:
    return f"INST:{short_hash('institution', fold(name))}"


def affiliation_country(affiliation: str | None) -> str | None:
    text = scrub_contacts(affiliation).strip().rstrip(".")
    if not text or "," not in text:
        return None
    last = text.split(";")[0].split(",")[-1].strip(" .")
    last = re.sub(r"\d", "", last).strip()
    return last if 2 <= len(last) <= 40 and not _INST_WORDS.search(last) else None


# ---------------------------------------------------------------------------------------------
# Scope term matching


# Phrases too generic to identify a single disease on their own.
GENERIC_TERMS = {
    "epilepsy",
    "seizures",
    "seizure",
    "epileptic encephalopathy",
    "epileptic encephalopathies",
    "developmental and epileptic encephalopathy",
    "developmental and epileptic encephalopathies",
    "early infantile epileptic encephalopathy",
    "infantile epileptic encephalopathy",
    "encephalopathy",
    "intellectual disability",
    "autism",
    "autism spectrum disorder",
    "neurodevelopmental disorder",
    "neurodevelopmental disorders",
    "developmental delay",
    "rare disease",
    "rare diseases",
    "genetic epilepsy",
    "drug resistant epilepsy",
    "refractory epilepsy",
    "focal epilepsy",
    "generalized epilepsy",
    "infantile spasms",
    "migraine",
    "ataxia",
    "disease",
    "syndrome",
}


# Connective words ignored when checking that a gene-qualified name's tokens all occur.
FILLER = {
    "related",
    "associated",
    "linked",
    "caused",
    "by",
    "mutation",
    "mutations",
    "in",
    "gene",
    "the",
    "of",
    "with",
    "due",
    "to",
    "a",
    "an",
    "and",
    "type",
}


@dataclass(frozen=True)
class Match:
    node_id: str
    method: str  # exact | phrase | gene_tokens
    term: str


class ScopeMatcher:
    """Matches free text (trial conditions, grant abstracts, LLM entity mentions) to scope ids.

    Only confident matches: exact name, a distinctive multi-word synonym contained as a whole
    phrase, or (for gene-qualified names such as "STXBP1 encephalopathy") all tokens present.
    A term shared by several diseases is ambiguous and never used.
    """

    def __init__(self, scope: Scope, extra_synonyms: Iterable[tuple[str, str]] = ()):
        self.scope = scope
        self.gene_symbols = {g["symbol"].upper(): g["hgnc_id"] for g in scope.genes}
        terms: dict[str, set[str]] = defaultdict(set)
        for d in scope.diseases:
            for t in [d.get("label"), *(d.get("synonyms") or [])]:
                if t:
                    terms[fold(t)].add(d["mondo_id"])
        for g in scope.genes:
            for t in [g.get("symbol"), *(g.get("aliases") or [])]:
                if t:
                    terms[fold(t)].add(g["hgnc_id"])
        for p in scope.phenotypes:
            for t in [p.get("label"), *(p.get("synonyms") or [])]:
                if t:
                    terms[fold(t)].add(p.get("hpo_id") or p.get("id"))
        in_scope = scope.disease_ids | scope.gene_ids | scope.phenotype_ids
        for node_id, syn in extra_synonyms:
            if node_id in in_scope and syn:
                terms[fold(syn)].add(node_id)
        self.terms = {t: ids for t, ids in terms.items() if t and len(ids) == 1}

    @cached_property
    def disease_terms(self) -> list[tuple[str, str]]:
        ids = self.scope.disease_ids
        out = [(t, next(iter(i))) for t, i in self.terms.items() if next(iter(i)) in ids]
        return sorted(out, key=lambda x: -len(x[0]))

    def _distinctive(self, term: str) -> bool:
        toks = term.split()
        return term not in GENERIC_TERMS and (len(toks) >= 2 and len(term) >= 8)

    def resolve(self, mention: str) -> str | None:
        """Exact (folded) lookup of a mention against every in-scope name, or None."""
        ids = self.terms.get(fold(mention))
        return next(iter(ids)) if ids else None

    def diseases_in(self, text: str | None, *, exact_only: bool = False) -> list[Match]:
        f = fold(text)
        if not f:
            return []
        hit = self.terms.get(f)
        if hit and next(iter(hit)) in self.scope.disease_ids:
            return [Match(next(iter(hit)), "exact", f)]
        if exact_only:
            return []
        padded = f" {f} "
        core = " " + " ".join(t for t in f.split() if t not in FILLER) + " "
        found: dict[str, Match] = {}
        for term, node_id in self.disease_terms:
            if node_id in found:
                continue
            if self._distinctive(term) and f" {term} " in padded:
                found[node_id] = Match(node_id, "phrase", term)
                continue
            toks = [t for t in term.split() if t not in FILLER]
            if (
                len(toks) >= 2
                and any(t.upper() in self.gene_symbols for t in toks)
                and f" {' '.join(toks)} " in core
                and term not in GENERIC_TERMS
            ):
                found[node_id] = Match(node_id, "gene_tokens", term)
        # Drop a match whose term is contained in a longer matched term of another disease.
        matches = list(found.values())
        return [
            m
            for m in matches
            if not any(o is not m and f" {m.term} " in f" {o.term} " for o in matches)
        ]


def load_scope_file(path: Path) -> Scope:
    data = json.loads(Path(path).read_text())
    return Scope(
        data_version=data.get("data_version", "dev"),
        genes=data.get("genes", []),
        diseases=data.get("diseases", []),
        phenotypes=data.get("phenotypes", []),
    )


def disease_query_terms(scope: Scope, disease: dict[str, Any], limit: int = 6) -> list[str]:
    """Distinctive search phrases for one disease: label and synonyms no other disease shares."""
    matcher = ScopeMatcher(scope)
    out: list[str] = []
    for t in [disease.get("label"), *(disease.get("synonyms") or [])]:
        if not t or "," in t or len(t) > 80:
            continue
        f = fold(t)
        if f not in matcher.terms or f in GENERIC_TERMS or len(f) < 5:
            continue
        # MONDO numbered labels ("developmental and epileptic encephalopathy 4") rarely appear
        # in text; skip trailing-number names unless they carry a gene symbol.
        has_gene = any(tok.upper() in matcher.gene_symbols for tok in f.split())
        if re.search(r"\b\d+[a-z]?$", f) and not has_gene:
            continue
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


async def request(client, method: str, url: str, *, pace: float = 0.0, attempts: int = 4, **kw):
    """One API call through the shared client, spaced by ``pace`` seconds, with an extra retry
    layer on top of the transport's (it also covers errors raised while handling a 429)."""
    import asyncio

    import httpx

    for attempt in range(attempts):
        if pace:
            await asyncio.sleep(pace)
        try:
            r = await client.request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                await asyncio.sleep(2**attempt * 2)
                continue
            r.raise_for_status()
            return r
        except (RuntimeError, httpx.TransportError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(2**attempt * 2)
    raise AssertionError("unreachable")


def json_attrs(**kwargs: Any) -> str:
    return json.dumps(
        {k: v for k, v in kwargs.items() if v not in (None, "", [], {})},
        ensure_ascii=False,
        sort_keys=True,
    )
