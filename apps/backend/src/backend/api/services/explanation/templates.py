"""Deterministic explanation text built from edge data (no LLM), plus the trust-rule sentences
that are appended in code when a generated text does not cover them."""

import re

from backend.api.services.explanation.common import (
    VUS_NOTICES,
    base_language,
    pick,
    split_sentences,
)
from backend.api.services.explanation.pathdata import PathData, has_contradiction
from backend.schemas.enums import EdgeStatus, Origin, Role, confidence_level
from backend.schemas.graph import Edge

TEMPLATE_LANGUAGES = ("en", "de")

RELATION_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "caused_by_variant_in": "{s} is caused by changes in the gene {t}",
        "acts_via": "{s} acts through {t}",
        "participates_in": "{s} takes part in {t}",
        "has_phenotype": "{s} can include {t}",
        "same_gene_same_mechanism": "{s} and {t} involve the same gene, working the same way",
        "same_gene_different_mechanism": "{s} and {t} involve the same gene, but it works "
        "in a different way in each",
        "shared_pathway": "{s} and {t} affect a shared biological pathway",
        "similar_symptoms": "{s} and {t} have similar symptoms (similar experience, possibly "
        "different cause)",
        "shared_researcher": "{s} and {t} are studied by the same researchers",
        "asserts": "{s} states that {t}",
        "authored": "{s} wrote {t}",
        "pi_of": "{s} leads the grant {t}",
        "funds_research_on": "{s} funds research on {t}",
        "serves": "{s} serves people with {t}",
        "runs": "{s} runs {t}",
        "studies": "{s} studies {t}",
        "investigator_of": "{s} is an investigator of {t}",
        "affiliated_with": "{s} works at {t}",
        "variant_of": "{s} is a variant in {t}",
        "observed_in": "{s} has been seen in people with {t}",
        "member_of": "{s} is a member of {t}",
        "about": "{s} is about {t}",
        "_default": "{s} is linked to {t}",
    },
    "de": {
        "caused_by_variant_in": "{s} wird durch Veränderungen im Gen {t} verursacht",
        "acts_via": "{s} wirkt über {t}",
        "participates_in": "{s} ist an {t} beteiligt",
        "has_phenotype": "Zu {s} kann {t} gehören",
        "same_gene_same_mechanism": "{s} und {t} betreffen dasselbe Gen auf dieselbe Weise",
        "same_gene_different_mechanism": "{s} und {t} betreffen dasselbe Gen, aber auf "
        "unterschiedliche Weise",
        "shared_pathway": "{s} und {t} betreffen einen gemeinsamen biologischen Signalweg",
        "similar_symptoms": "{s} und {t} haben ähnliche Symptome (ähnliche Erfahrung, "
        "möglicherweise andere Ursache)",
        "shared_researcher": "{s} und {t} werden von denselben Forschenden untersucht",
        "asserts": "{s} stellt fest: {t}",
        "authored": "{s} hat {t} verfasst",
        "pi_of": "{s} leitet die Förderung {t}",
        "funds_research_on": "{s} fördert Forschung zu {t}",
        "serves": "{s} unterstützt Menschen mit {t}",
        "runs": "{s} betreibt {t}",
        "studies": "{s} untersucht {t}",
        "investigator_of": "{s} ist Prüfärztin oder Prüfarzt von {t}",
        "affiliated_with": "{s} arbeitet an {t}",
        "variant_of": "{s} ist eine Variante in {t}",
        "observed_in": "{s} wurde bei Menschen mit {t} beobachtet",
        "member_of": "{s} ist Mitglied von {t}",
        "about": "{s} handelt von {t}",
        "_default": "{s} ist mit {t} verbunden",
    },
}

NOTES: dict[str, dict[str, str]] = {
    "hypothesis": {
        "en": "The link {c} is a hypothesis computed from the data, not an observed fact.",
        "de": "Die Verbindung {c} ist eine aus den Daten berechnete Hypothese, keine "
        "beobachtete Tatsache.",
    },
    "reported": {
        "en": "The link {c} was reported by users and is not verified yet.",
        "de": "Die Verbindung {c} wurde von Nutzerinnen und Nutzern gemeldet und ist noch "
        "nicht geprüft.",
    },
    "review": {
        "en": "The link {c} is under review.",
        "de": "Die Verbindung {c} wird gerade überprüft.",
    },
    "contradiction": {
        "en": "Some sources contradict the link {c}.",
        "de": "Einige Quellen widersprechen der Verbindung {c}.",
    },
}

_HEDGE = {
    "en": r"\b(may|might|could|possibl\w*|perhaps|hypothes\w*|suggest\w*|likely|unconfirmed|"
    r"computed|predicted|not (yet )?(proven|confirmed|observed))\b",
    "de": r"(möglich\w*|vielleicht|könnte\w*|hypothese|vermutlich|wahrscheinlich|berechnet\w*|"
    r"nicht (bestätigt|belegt|beobachtet))",
}
_CONTRA = {
    "en": r"(contradict\w*|conflict\w*|disagree\w*|disput\w*|inconsistent|not all sources)",
    "de": r"(widersprech\w*|widerspr\w*|uneinig|nicht alle quellen)",
}
_REVIEW = {"en": r"\breview\w*\b", "de": r"(überprüf\w*|prüfung)"}

TIER_WORDS = {
    "curated_db": "curated database",
    "peer_reviewed": "peer-reviewed study",
    "review": "review article",
    "preprint": "preprint",
    "llm_inferred": "computed by AI from text",
    "patient_reported": "patient-reported",
}


def cite(edge_id: str) -> str:
    return f"[{edge_id}]"


def note(kind: str, language: str, edge_id: str) -> str:
    return pick(NOTES[kind], language).format(c=cite(edge_id))


def relation_sentence(data: PathData, edge: Edge, language: str) -> str:
    phrases = RELATION_PHRASES.get(base_language(language), RELATION_PHRASES["en"])
    phrase = phrases.get(edge.relation.value, phrases["_default"])
    text = phrase.format(s=data.node_label(edge.source_id), t=data.node_label(edge.target_id))
    return text[0].upper() + text[1:]


def _detail(data: PathData, edge: Edge, role: Role) -> str:
    if role not in (Role.doctor, Role.researcher):
        return ""
    level = confidence_level(edge.confidence).value
    tiers = sorted({ev.tier for ev in data.supporting(edge.id)})
    tier_text = ", ".join(TIER_WORDS.get(t, t) for t in tiers) or "no evidence rows"
    ids = f"; {edge.source_id} → {edge.target_id}" if role == Role.researcher else ""
    return f" (confidence {edge.confidence:.2f}, {level}; {tier_text}{ids})"


SUBJECT_LEADS: dict[str, dict[str, str]] = {
    "en": {
        "lead": "Here is how {s} is connected in the atlas, strongest links first.",
        "none": "The atlas lists no links for {s} here.",
    },
    "de": {
        "lead": "So ist {s} im Atlas verbunden, die stärksten Verbindungen zuerst.",
        "none": "Der Atlas zeigt hier keine Verbindungen für {s}.",
    },
}


def template_explanation(data: PathData, role: Role, language: str) -> str:
    """Honest, deterministic explanation from the edge data alone, one sentence per edge. A
    subject summary opens with a lead sentence and lists the links strongest first."""
    lang = base_language(language) if base_language(language) in TEMPLATE_LANGUAGES else "en"
    sentences: list[str] = []
    edges = data.ordered_edges()
    if data.subject_id:
        edges.sort(key=lambda e: -e.confidence)
        leads = SUBJECT_LEADS[lang]
        name = data.node_label(data.subject_id)
        sentences.append((leads["lead"] if edges else leads["none"]).format(s=name))
    for edge in edges:
        sentences.append(
            relation_sentence(data, edge, lang)
            + (_detail(data, edge, role) if lang == "en" else "")
            + f" {cite(edge.id)}."
        )
        if edge.origin == Origin.inferred:
            sentences.append(note("hypothesis", lang, edge.id))
        elif edge.origin in (Origin.patient_reported, Origin.user_contributed):
            sentences.append(note("reported", lang, edge.id))
        if edge.status != EdgeStatus.active:
            sentences.append(note("review", lang, edge.id))
        if has_contradiction(edge, data):
            sentences.append(note("contradiction", lang, edge.id))
    if data.vus_nodes():
        sentences.append(pick(VUS_NOTICES, lang))
    return " ".join(sentences)


def _sentences_citing(text: str, edge_id: str) -> list[str]:
    return [s for s in split_sentences(text) if edge_id in s]


def _covered(sentences: list[str], patterns: dict[str, str], language: str) -> bool:
    pattern = patterns.get(base_language(language))
    if pattern is None:
        return True  # no word list for this language: rely on the prompt
    return any(re.search(pattern, s, re.IGNORECASE) for s in sentences)


def enforce_trust_rules(text: str, data: PathData, language: str) -> tuple[str, list[str]]:
    """Append the standard sentence for every trust rule the text does not cover itself:
    inferred = hypothesis, contradicting evidence, non-active = under review, VUS notice."""
    added: list[str] = []
    for edge in data.ordered_edges():
        near = _sentences_citing(text, edge.id)
        if edge.origin == Origin.inferred and not _covered(near, _HEDGE, language):
            added.append(note("hypothesis", language, edge.id))
        if edge.origin in (Origin.patient_reported, Origin.user_contributed) and not _covered(
            near, _HEDGE, language
        ):
            added.append(note("reported", language, edge.id))
        if edge.status != EdgeStatus.active and not _covered(near, _REVIEW, language):
            added.append(note("review", language, edge.id))
        if has_contradiction(edge, data) and not _covered(near, _CONTRA, language):
            added.append(note("contradiction", language, edge.id))
    if data.vus_nodes():
        vus = pick(VUS_NOTICES, language)
        if vus not in text:
            added.append(vus)
    if not added:
        return text, []
    return text.rstrip() + " " + " ".join(added), added
