"""Helpers shared by the explanation service, the chat orchestrator and the proposal export."""

import re

import textstat

from backend.llm import LLMError
from backend.schemas.enums import VUS_NOTICE, ErrorCode, Role

EDGE_ID_RE = re.compile(r"\be_[0-9a-f]{12}\b")
_CITATION_GROUP_RE = re.compile(r"\s*\[\s*e_[0-9a-f]{12}(?:\s*[,;]\s*e_[0-9a-f]{12})*\s*\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-ZÄÖÜ0-9])")

# Flesch-Kincaid grade targets per lens. Patients and guests: grade 8 (spec). Doctors and
# researchers read clinical and technical prose, so the gate only stops runaway jargon there.
GRADE_TARGETS: dict[Role, float] = {
    Role.guest: 8.0,
    Role.patient: 8.0,
    Role.doctor: 14.0,
    Role.researcher: 16.0,
}

LANGUAGE_NAMES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "cs": "Czech",
    "tr": "Turkish",
}

VUS_NOTICES = {
    "en": VUS_NOTICE,
    "de": "Dieses Ergebnis ist unsicher. Besprechen Sie es mit einer genetischen Beratung, "
    "bevor Sie danach handeln.",
}

AI_NOTICES = {
    "en": "Dr. Wu is an AI system, not a doctor. Answers come from the atlas's cited sources "
    "and can be wrong.",
    "de": "Dr. Wu ist ein KI-System, keine Ärztin und kein Arzt. Die Antworten stammen aus den "
    "zitierten Quellen des Atlas und können falsch sein.",
}

_GERMAN_WORDS = frozenset(
    "und nicht ich ist mein meine unser unsere hat mit der die das kein keine wir sie er seit "
    "auch sehr bei von wie was wird sind haben eine einen ein noch".split()
)


def base_language(language: str | None) -> str:
    return (language or "en").split("-")[0].lower()


def language_name(language: str) -> str:
    return LANGUAGE_NAMES.get(base_language(language), language)


def pick(texts: dict[str, str], language: str) -> str:
    """Fixed server text in the lens language (English fallback)."""
    return texts.get(base_language(language), texts["en"])


def looks_german(text: str) -> bool:
    words = re.findall(r"[a-zäöüß]+", text.lower())
    hits = sum(w in _GERMAN_WORDS for w in words)
    return hits >= 2 or (hits >= 1 and bool(re.search(r"[äöüß]", text.lower())))


def strip_citations(text: str) -> str:
    return _CITATION_GROUP_RE.sub("", text)


def cited_edges(text: str) -> list[str]:
    return list(dict.fromkeys(EDGE_ID_RE.findall(text)))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def reading_grade(text: str, language: str) -> float | None:
    """Flesch-Kincaid grade. textstat's grade formula is calibrated for English only, so other
    languages get None (no gate)."""
    if base_language(language) != "en":
        return None
    clean = strip_citations(text).strip()
    if not clean:
        return None
    return round(float(textstat.flesch_kincaid_grade(clean)), 1)


def passes_grade(grade: float | None, role: Role) -> bool:
    return grade is None or grade <= GRADE_TARGETS.get(role, 8.0)


LLM_ERRORS: dict[str, tuple[ErrorCode, str]] = {
    "usage_limit_exceeded": (
        ErrorCode.rate_limited,
        "Your ChatGPT plan's usage limit is reached. Please try again later.",
    ),
    "usage_unavailable": (
        ErrorCode.upstream_error,
        "ChatGPT plan usage is not available for this account right now.",
    ),
    "reauth_required": (ErrorCode.sign_in_required, "Please sign in with ChatGPT again."),
    "timeout": (ErrorCode.upstream_error, "Dr. Wu took too long to answer. Please try again."),
    "bad_output": (
        ErrorCode.upstream_error,
        "Dr. Wu could not produce a checked answer. Please try again.",
    ),
    "upstream": (ErrorCode.upstream_error, "The AI service failed. Please try again."),
}


def llm_error(exc: LLMError) -> tuple[ErrorCode, str]:
    return LLM_ERRORS.get(exc.code, LLM_ERRORS["upstream"])


def chunk_text(text: str, words: int = 4) -> list[str]:
    """Split text into small word groups for streaming deltas (joined they equal `text`)."""
    parts = re.findall(r"\S+\s*", text)
    return ["".join(parts[i : i + words]) for i in range(0, len(parts), words)] or [text]
