"""Helpers shared by the explanation service, the chat orchestrator and the proposal export."""

import re

import textstat
from textstat.textstat import textstatistics

from backend.llm import LLMError
from backend.schemas.enums import VUS_NOTICE, ErrorCode, Role

EDGE_ID_RE = re.compile(r"\be_[0-9a-f]{12}\b")
_CITATION_GROUP_RE = re.compile(r"\s*\[\s*e_[0-9a-f]{12}(?:\s*[,;]\s*e_[0-9a-f]{12})*\s*\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-ZÄÖÜ0-9])")


def _grade_targets() -> dict[Role, float]:
    """Flesch-Kincaid targets per lens, from the graph service's role hints (one source of
    truth: guest 6, patient 8, doctor 12, researcher 14)."""
    from backend.api.services.graph import ROLE_HINTS

    return {
        role: float(h.reading_grade_target) if h.reading_grade_target is not None else 8.0
        for role, h in ROLE_HINTS.items()
    }


GRADE_TARGETS: dict[Role, float] = _grade_targets()

# German is graded with the first Wiener Sachtextformel, which estimates a German school year
# (4 = very easy ... 15 = very hard), the same unit as the Flesch-Kincaid US grade. German
# compounds make it run higher on equivalent text, so each role's grade target gets this
# allowance (guest 8, patient 10, doctor 14, researcher 16).
GERMAN_GRADE_ALLOWANCE = 2.0

# A separate textstat instance for German, so the module-level (English) one never changes
# language under concurrent requests.
_GERMAN = textstatistics()
_GERMAN.set_lang("de")

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
    """School-grade reading level: Flesch-Kincaid for English, Wiener Sachtextformel for
    German. textstat has no grade formula calibrated for the other languages the UI may get,
    so they return None (no gate)."""
    lang = base_language(language)
    if lang not in ("en", "de"):
        return None
    clean = strip_citations(text).strip()
    if not clean:
        return None
    if lang == "de":
        return round(float(_GERMAN.wiener_sachtextformel(clean, 1)), 1)
    return round(float(textstat.flesch_kincaid_grade(clean)), 1)


def grade_target(role: Role, language: str = "en") -> float:
    """The role's reading-grade target on the scale reading_grade uses for the language."""
    target = GRADE_TARGETS.get(role, 8.0)
    if base_language(language) == "de":
        target += GERMAN_GRADE_ALLOWANCE
    return target


def passes_grade(grade: float | None, role: Role, language: str = "en") -> bool:
    return grade is None or grade <= grade_target(role, language)


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
