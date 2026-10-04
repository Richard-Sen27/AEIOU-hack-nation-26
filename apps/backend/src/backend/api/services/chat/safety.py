"""Rule-based safety: emergency detection (runs before any model call) and the medical boundary
(diagnosis, treatment choice, dosing, unrequested prognosis, variant reclassification).

English and German patterns; other languages fall back to the system prompt rules."""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from backend.api.services.explanation.common import pick, split_sentences


class Category(StrEnum):
    diagnosis = "diagnosis"
    treatment = "treatment"
    dosing = "dosing"
    prognosis = "prognosis"
    reclassification = "reclassification"


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


EMERGENCY = _rx(
    # breathing, colour, consciousness
    r"\b(not|isn'?t|is not|stopped|can'?t|cannot|can not|unable to|struggling to) breath(e|ing)\b",
    r"\bturn(ing|ed) (blue|purple|gr[ae]y)\b",
    r"\b(blue|purple) lips\b",
    r"\b(unconscious|unresponsive|passed out|won'?t wake( up)?|not waking up)\b",
    r"\bcan'?t wake (him|her|them|my \w+)",
    # ongoing seizure
    r"\bseiz\w*\b[^.?!]{0,40}\b(won'?t stop|not stopping|still going|for (over |more than )?"
    r"\d+ ?(min|minutes))",
    r"\b(seizing|convulsing|fitting) (right )?now\b",
    r"\bhaving a seizure (right )?now\b",
    # crisis
    r"\b(kill (myself|me)|suicid\w*|end (it all|my life)|want to die|don'?t want to (live|be "
    r"alive)|self[- ]harm|hurt(ing)? myself)\b",
    r"\boverdos\w*",
    r"\bswallowed\b[^.?!]{0,30}\b(pills|tablets|medication|bleach)\b",
    r"\bchest pain\b",
    # German
    r"\batmet (nicht|kaum)\b",
    r"\b(bekommt |kriegt )?keine luft\b",
    r"\b(blau|bläulich) (an)?gelaufen\b",
    r"\bblaue lippen\b",
    r"\b(bewusstlos|ohnmächtig|nicht ansprechbar|reagiert nicht( mehr)?|wacht nicht (mehr )?auf)\b",
    r"\b(krampf\w*|anfall)\b[^.?!]{0,40}\b(hört nicht auf|seit \d+ ?(min|minuten)|immer noch)",
    r"\bkrampft (gerade|jetzt|seit)\b",
    r"\b(umbringen|suizid\w*|selbstmord\w*|nicht mehr leben|das leben nehmen|will sterben|"
    r"selbstverletz\w*)",
    r"\büberdosis\b",
    r"\btabletten geschluckt\b",
    r"\bbrustschmerz\w*",
)

EMERGENCY_REPLY = {
    "en": "This sounds like an emergency. Please call your local emergency number now "
    "(112 in Europe, 911 in the US). Dr. Wu is an AI and cannot help in an emergency.",
    "de": "Das klingt nach einem Notfall. Bitte rufen Sie sofort den Notruf an (112 in Europa). "
    "Dr. Wu ist eine KI und kann in einem Notfall nicht helfen.",
}

_MED = (
    r"(drug|medication|medicine|treatment|therapy|pill|tablet|dose|valproate|stiripentol|"
    r"fenfluramine|cannabidiol|ketogenic diet|levetiracetam|carbamazepine|phenytoin|topiramate|"
    r"ezogabine|gene therapy|antisense|aso)"
)
_MED_DE = r"(medikament\w*|therapie\w*|behandlung\w*|tablette\w*|dosis|gentherapie)"
_DISEASE = r"(syndrome|disease|disorder|encephalopathy|epilepsy|condition|dravet)"
_DISEASE_DE = r"(syndrom|krankheit|erkrankung|epilepsie|enzephalopathie|dravet)"

ASKED: dict[Category, re.Pattern[str]] = {
    Category.diagnosis: _rx(
        r"\b(can|could|would|will) you diagnose\b",
        r"\b(what|which) (is|would be) (the|her|his|their|my|our) diagnosis\b",
        r"\bis (this|that|it) the (right |correct )?diagnosis\b",
        r"\b(give|make) (me |us )?a diagnosis\b",
        r"\b(does|do|could|might) (my|our|he|she|they|the) (\w+ )?(have|has)\b[^.?!]*\b" + _DISEASE,
        r"\bwhat (does|do) (he|she|they|my \w+|our \w+) have\b",
        r"\b(is|could) (it|this|that) be\b[^.?!]*\b" + _DISEASE,
        r"\b(hat|haben) (er|sie|mein \w+|meine \w+|unser \w+|unsere \w+)\b[^.?!]*" + _DISEASE_DE,
        r"\bwelche (krankheit|erkrankung) (hat|haben)\b",
        r"\bkönnte (es|das)\b[^.?!]*" + _DISEASE_DE + r"\w* sein\b",
        r"\b(stellen|stelle|stellst) (sie |du )?(eine|die) diagnose\b",
    ),
    Category.treatment: _rx(
        r"\b(which|what) " + _MED + r"s?\b[^.?!]*\b(should|best|recommend|take|try|use|give)",
        r"\bshould (i|we|she|he|they) (take|try|start|stop|switch|use|give)\b[^.?!]*\b" + _MED,
        r"\b(recommend|best) (a |the )?" + _MED,
        r"\b" + _MED_DE + r"\b[^.?!]*\b(soll\w*|empfehl\w*|besser|beste)",
        r"\bsollen wir\b[^.?!]*\b(geben|nehmen|absetzen|starten|wechseln)\b",
    ),
    Category.dosing: _rx(
        r"\bdos(e|es|age|ing)\b",
        r"\b\d+(\.\d+)?\s?mg\b",
        r"\bhow (much|many)\b[^.?!]*\b(give|take|mg|pills|tablets)\b",
        r"\b(dosis|dosierung)\b",
        r"\bwie viel\b[^.?!]*\b(geben|nehmen)\b",
    ),
    Category.prognosis: _rx(
        r"\blife expectancy\b",
        r"\bhow long\b[^.?!]*\blive\b",
        r"\bprognos\w*",
        r"\bsurviv\w*",
        r"\bmortality\b",
        r"\bdie (from|of|early|young)\b",
        r"\b(lebenserwartung|prognose|sterblichkeit)\b",
        r"\bsterb\w*",
        r"\büberleb\w*",
    ),
    Category.reclassification: _rx(
        r"\breclassif\w*",
        r"\b(vus|variant)\b[^.?!]*\b(really|actually|truly) (pathogenic|benign|harmful|harmless|"
        r"disease[- ]causing)",
        r"\bis (my|the|this|our) (vus|variant)\b[^.?!]*\b(pathogenic|benign|harmful|harmless|"
        r"the cause)",
        r"\bumklassifi\w*",
        r"\b(variante|vus)\b[^.?!]*\b(wirklich|eigentlich) (pathogen|harmlos|"
        r"krankheitsverursachend)",
    ),
}

STATED: dict[Category, re.Pattern[str]] = {
    Category.diagnosis: _rx(
        r"\b(your|the) (child|daughter|son|baby|kid|patient)\b[^.]*\b(has|is suffering from|is "
        r"diagnosed with|most likely has|probably has)\b",
        r"\byou (have|likely have|probably have|most likely have|are suffering from)\b",
        r"\b(she|he|they) (has|have|likely has|probably has|most likely has) (a |an )?[^.]*\b"
        r"(syndrome|disease|disorder|encephalopathy|epilepsy)\b",
        r"\b(the|a|your) diagnosis (is|would be|must be)\b",
        r"\bthis is (likely |probably |definitely |clearly )?(a case of )?\w+ syndrome\b",
        # a symptom overlap given as a probability, likelihood or percentage
        r"\b(probability|likelihood|chance|odds)\b[^.]{0,30}\b(of having|that (you|your \w+|he|"
        r"she|they|it is|this is))\b",
        r"\b\d{1,3}(?:[.,]\d+)?\s?% (chance|likely|likelihood|probability|match|sure|certain)\b",
        r"\b(you|your \w+|he|she|they) (are|is) (very |most |more )?likely to (have|has)\b",
        r"\b(ihr|ihre|dein|deine) (kind|tochter|sohn|baby)\b[^.]*\b(hat|leidet an)\b",
        r"\b(die )?diagnose (ist|lautet|wäre)\b",
    ),
    Category.treatment: _rx(
        r"\byou should (take|start|stop|try|give|switch|use|get)\b",
        r"\b(i|we) (recommend|suggest|advise)\b[^.]*\b(drug|medication|medicine|treatment|"
        r"therapy|dose)",
        r"\b(start|try|give) (him|her|them|your \w+) (on )?[^.]*\b" + _MED,
        r"\bsie sollten\b[^.]*\b(nehmen|geben|absetzen|beginnen|wechseln)\b",
        r"\b(ich|wir) empfehle\w*\b[^.]*\b(medikament|therapie|behandlung|dosis)",
    ),
    Category.dosing: _rx(
        r"\b\d+(\.\d+)?\s?mg(/kg)?\b",
        r"\b(recommended|typical|usual) dos(e|age)\b",
        r"\b(empfohlene|übliche) dosis\b",
    ),
    Category.prognosis: _rx(
        r"\blife expectancy\b",
        r"\bmortality\b",
        r"\bsurvival (rate|of|to)\b",
        r"\b\d+\s?% (of (patients|children|people) )?(die|survive)",
        r"\b(die|death)s?\b[^.]*\b(by|before) (the )?age\b",
        r"\b(lebenserwartung|sterblichkeit|überlebensrate)\b",
    ),
    Category.reclassification: _rx(
        r"\b(variant|vus)\b[^.]*\b(is|should be|can be|must be) (re)?classified\b",
        r"\b(this|your|the) (variant|vus) is (likely |probably |actually )?(pathogenic|benign|"
        r"disease[- ]causing|harmless)\b",
        r"\b(variante|vus)\b[^.]*\b(ist|wäre) (wahrscheinlich )?(pathogen|harmlos)\b",
    ),
}

DECLINE = {
    Category.diagnosis: {
        "en": "I can't say if this is the diagnosis. Only a doctor can, such as a clinical "
        "geneticist. Here is what the atlas links, to talk over with them.",
        "de": "Ob das die Diagnose ist, kann ich nicht sagen. Das kann nur eine Ärztin oder ein "
        "Arzt, etwa in der Humangenetik. Hier ist, was der Atlas verbindet, zum Besprechen.",
    },
    Category.treatment: {
        "en": "I can't choose a treatment. Please ask your doctor. Here is what the atlas "
        "links, to talk over with them.",
        "de": "Eine Behandlung kann ich nicht auswählen. Bitte fragen Sie Ihre Ärztin oder Ihren "
        "Arzt. Hier ist, was der Atlas verbindet, zum Besprechen.",
    },
    Category.dosing: {
        "en": "I can't give doses. Please ask your doctor. Here is what the atlas links, "
        "to talk over with them.",
        "de": "Dosierungen kann ich nicht nennen. Bitte fragen Sie Ihre Ärztin oder Ihren Arzt. "
        "Hier ist, was der Atlas verbindet, zum Besprechen.",
    },
    Category.prognosis: {
        "en": "I don't give outlook or survival figures unless you ask. Here is what the atlas "
        "links.",
        "de": "Zahlen zu Verlauf oder Lebenserwartung nenne ich nur auf Nachfrage. Hier ist, was "
        "der Atlas verbindet.",
    },
    Category.reclassification: {
        "en": "I can't reclassify a variant. A genetic counselor can review it with you. Here "
        "is what the atlas shows about it.",
        "de": "Eine Variante kann ich nicht neu einstufen. Eine genetische Beratung kann sie mit "
        "Ihnen prüfen. Hier ist, was der Atlas dazu zeigt.",
    },
}

DECLINE_ORDER = (
    Category.diagnosis,
    Category.reclassification,
    Category.treatment,
    Category.dosing,
    Category.prognosis,
)

SYSTEM_PROMPT_HINT = (
    "The user's message asks for {what}. Do not answer that part: no diagnosis, treatment "
    "choice, dosing or variant reclassification. Still use the tools and give the graph "
    "context (related diseases, groups, assets) with cited claims."
)


def is_emergency(text: str) -> bool:
    return bool(EMERGENCY.search(text))


def emergency_reply(language: str) -> str:
    return pick(EMERGENCY_REPLY, language)


def asked_categories(text: str) -> set[Category]:
    """Boundary categories the user's message asks for (prognosis is allowed when asked)."""
    return {cat for cat, rx in ASKED.items() if rx.search(text)}


def stated_categories(text: str, *, prognosis_asked: bool) -> set[Category]:
    found = {cat for cat, rx in STATED.items() if rx.search(text)}
    if prognosis_asked:
        found.discard(Category.prognosis)
    return found


@dataclass
class FilterResult:
    text: str
    removed: list[Category] = field(default_factory=list)


def filter_sentences(text: str, *, prognosis_asked: bool) -> FilterResult:
    """Drop sentences that diagnose, choose treatment, dose, reclassify, or give unrequested
    prognosis."""
    kept: list[str] = []
    removed: list[Category] = []
    for sentence in split_sentences(text):
        cats = stated_categories(sentence, prognosis_asked=prognosis_asked)
        if cats:
            removed.extend(sorted(cats))
        else:
            kept.append(sentence)
    return FilterResult(" ".join(kept), removed)


def decline_sentence(categories: set[Category], language: str) -> str | None:
    for cat in DECLINE_ORDER:
        if cat in categories:
            return pick(DECLINE[cat], language)
    return None
