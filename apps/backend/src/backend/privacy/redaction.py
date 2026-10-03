"""Personal-data redaction with Microsoft Presidio, run before any LLM call on user content.

Removes names, birth dates, street addresses, e-mail, phone numbers and patient / record /
insurance identifiers (English, plus regex coverage for German/Austrian documents) while keeping
medical content: gene symbols, HGVS, ontology ids, eponymous disease names, ages, test dates and
country names.
"""

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field

from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    IpRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
    UsSsnRecognizer,
)

SPACY_MODEL = "en_core_web_lg"

PLACEHOLDERS = {
    "PERSON": "<PERSON>",
    "DATE_OF_BIRTH": "<DATE_OF_BIRTH>",
    "STREET_ADDRESS": "<ADDRESS>",
    "LOCATION": "<LOCATION>",
    "EMAIL_ADDRESS": "<EMAIL>",
    "PHONE_NUMBER": "<PHONE>",
    "PATIENT_ID": "<ID>",
    "US_SSN": "<ID>",
    "IBAN_CODE": "<ID>",
    "CREDIT_CARD": "<ID>",
    "IP_ADDRESS": "<IP_ADDRESS>",
}
ENTITIES = list(PLACEHOLDERS)

# Recognizers whose match is explicit context ("DOB:", "Patient:", "MRN") beat medical heuristics.
_LABELED = "labeled"

_MONTHS = (
    r"(?:Jan(?:uary|uar)?|J[äa]nner|Feb(?:ruary|ruar)?|Feber|M[äa]r(?:ch|z)?|Maerz|Apr(?:il)?|"
    r"Ma[yi]|Jun[ei]?|Jul[yi]?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|O[ck]t(?:ober)?|Nov(?:ember)?|"
    r"De[cz](?:ember)?)\.?"
)
_DATE = (
    r"(?:\d{1,2}[./-]\s?\d{1,2}[./-]\s?\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?\s"
    + _MONTHS
    + r"\s\d{4}|"
    + _MONTHS
    + r"\s\d{1,2}(?:st|nd|rd|th)?,?\s\d{4})"
)
_DOB_LABEL = (
    r"(?i:date\s+of\s+birth|birth\s*date|d\.?\s?o\.?\s?b\.?|born(?:\s+on)?|b\.|"
    r"geburtsdatum|geb\.?\s?-?\s?dat(?:um|\.)?|geb\.|geboren(?:\s+am)?|date\s+de\s+naissance|"
    r"n[ée]e?\s+le)"
)
_DOB_RE = re.compile(r"(?<!\w)" + _DOB_LABEL + r"[ \t]*[:=]?[ \t]*(?P<v>" + _DATE + r")")

_NAME = (
    r"(?!(?:Dr|Prof|Med|Univ|Mag|Ing|DI|OA|Prim)\b)"
    r"[A-ZÄÖÜ][\w'’\-]+(?:,?[ \t][A-ZÄÖÜ][\w'’\-]+){0,2}"
)
_COLON_LABELS = (
    r"(?i:patient(?:in)?(?:\s*name)?|name|full\s+name|patientenname|pat\.|vorname|nachname|"
    r"familienname|surname|first\s+name|last\s+name|mother|father|mutter|vater|child|kind|"
    r"proband(?:in)?|parent|guardian|erziehungsberechtigte?r?|referring\s+(?:physician|doctor)|"
    r"zuweiser(?:in)?|einsender(?:in)?|signed|gez\.|physician|arzt|ärztin|contact)"
)
_HONORIFICS = (
    r"(?:Herrn?|Frau|Hr\.|Fr\.|Mr\.?|Mrs\.?|Ms\.?|Miss|Dear|Sehr\s+geehrte[r]?(?:\s+(?:Herr|Frau))?|"
    r"Dr\.(?:\s?med\.)?(?:\s?univ\.)?|Prof\.(?:\s?Dr\.)?|OA|OÄ|Prim\.)"
)
_NAME_RES = [
    re.compile(
        r"(?<!\w)"
        + _COLON_LABELS
        + r"[ \t]*:[ \t]*(?:"
        + _HONORIFICS
        + r"[ \t]+)*(?P<v>"
        + _NAME
        + ")"
    ),
    re.compile(r"(?<![\w.])(?:" + _HONORIFICS + r"[ \t]+)+(?P<v>" + _NAME + ")"),
]

_ID_LABEL = (
    r"(?i:mrn|medical\s+record\s*(?:number|no\.?|#)?|patient\s*(?:id|number|no\.?|#)|"
    r"record\s*(?:id|number|no\.?|#)|case\s*(?:id|number|no\.?|#)|chart\s*(?:number|no\.?)|"
    r"insurance\s*(?:id|number|no\.?|#)|member\s*(?:id|number|no\.?)|policy\s*(?:number|no\.?)|"
    r"ssn|social\s+security\s+(?:number|no\.?)|nhs\s+(?:number|no\.?)|health\s+card\s*(?:no\.?)?|"
    r"sozialversicherungs-?(?:nummer|nr\.?)|sv-?nr\.?|svnr|versicherungs-?(?:nummer|nr\.?)|"
    r"versicherten-?(?:nummer|nr\.?)|patienten-?(?:id|nummer|nr\.?)|fall-?(?:nummer|nr\.?|zahl)|"
    r"aufnahme-?(?:nummer|zahl|nr\.?)|befund-?(?:nummer|nr\.?)|auftrags-?(?:nummer|nr\.?)|"
    r"labor-?(?:nummer|nr\.?)|einsende-?(?:nummer|nr\.?)|proben-?(?:nummer|nr\.?)|"
    r"lab(?:oratory)?\s*(?:id|no\.?|number|#)|sample\s*(?:id|no\.?|number|#)|"
    r"specimen\s*(?:id|no\.?|number|#)|accession\s*(?:no\.?|number|#)|"
    r"order\s*(?:id|no\.?|number|#)|requisition\s*(?:no\.?|number|#)|"
    r"identifier|id\s*(?:no\.?|number))"
)
_ID_VALUE = (
    r"(?P<v>(?:[A-Z]{1,5}[-/ ]?)?\d[\dA-Z]*(?:[-/.]\d[\dA-Z]*|[-/][A-Z]+\d*|\s\d{2,}[\dA-Z]*)*)"
)
_ID_RE = re.compile(_ID_LABEL + r"\s*[:#.]?\s*(?:[:#]\s*)?" + _ID_VALUE)
_SVNR_RE = re.compile(r"(?<!\d)(?P<v>\d{4}\s?(?:0[1-9]|[12]\d|3[01])(?:0[1-9]|1[0-2])\d{2})(?!\d)")

_STREET_EN = (
    r"(?P<v>\d{1,5}[A-Za-z]?\s+(?:[A-Z][a-z]+\.?\s){1,3}(?:Street|St\.|Avenue|Ave\.?|Road|Rd\.?|"
    r"Boulevard|Blvd\.?|Lane|Ln\.?|Drive|Court|Ct\.?|Way|Place|Pl\.?|Terrace|Close|Crescent|"
    r"Parkway|Highway|Square)(?:,?\s*(?:Apt|Apartment|Unit|Suite|Flat|#)\.?\s*[\w-]+)?)"
)
_STREET_DE_SUFFIX = (
    r"(?:straße|strasse|str\.|gasse|weg|platz|allee|ring|gürtel|kai|ufer|zeile|steig|damm|markt|"
    r"stiege|hof)"
)
_STREET_DE = (
    r"(?P<v>(?:[A-ZÄÖÜ][\wäöüß\-]*"
    + _STREET_DE_SUFFIX
    + r"|(?:[A-ZÄÖÜ][\wäöüß\-]+\s)(?:Straße|Strasse|Str\.|Gasse|Weg|Platz|Allee|Ring|Gürtel|"
    r"Kai|Ufer|Zeile|Damm|Markt))\s+\d{1,4}[a-z]?(?:\s?[/-]\s?\d{1,4}[a-z]?)*"
    r"(?:\s?(?:Top|Stiege|Tür|Stg\.?)\s?\d+)*)"
)
_POSTAL_CITY = (
    r"(?m:(?:(?<=,\s)|(?<=,)|(?<=\n)|^)\s*(?P<v>(?:A-|AT-|D-|DE-|CH-)?\d{4,5}\s+[A-ZÄÖÜ]"
    r"[\wäöüß\-]+(?:\s(?:am|an\sder|im|bei|ob\sder)\s[A-ZÄÖÜ][\wäöüß]+)?))"
)
_US_CITY_ZIP = r"(?P<v>[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?,\s[A-Z]{2}\s\d{5}(?:-\d{4})?)"
_PO_BOX = r"(?P<v>(?i:p\.?\s?o\.?\s?box|postfach)\s\d+)"
# Continental European street forms, number before or after the street word ("14 Via Roma",
# "Via Roma 14", "12 rue de la Paix", "Calle Mayor 5", "Kalverstraat 12"). Every form needs a
# house number next to a capitalised street name, so prose like "via the pathway", "acts via
# Notch" or "West syndrome" never matches; the lower-case street word is only accepted for the
# French/Iberian words that are conventionally written that way, and only after a number.
_EU_STREET_WORDS = (
    r"(?:Via|Viale|Vicolo|Piazza|Piazzale|Corso|Largo|Strada|Rue|Avenue|Av\.|Boulevard|Bd\.?|"
    r"Chemin|Allée|Impasse|Place|Quai|Route|Calle|Avenida|Avda\.|Plaza|Paseo|Carrer|Camino|"
    r"Carretera|Ronda|Travesía|Rua|Praça|Travessa|Estrada|Straat|Laan|Weg|Gasse|Platz|Allee|"
    r"Ulica|Ul\.)"
)
_EU_LOWER_WORDS = (
    r"(?:rue|avenue|boulevard|chemin|allée|impasse|place|quai|calle|avenida|plaza|paseo|carrer|"
    r"camino|rua|praça|travessa|estrada)"
)
_EU_CONNECTOR = (
    r"(?:de|del|della|delle|dei|degli|di|da|du|des|la|le|les|dos|das|do|van|von|der|den|het|"
    r"y|e|al|alla|d'|l')"
)
_EU_NAME = (
    r"(?:" + _EU_CONNECTOR + r"[ \t]+|d'|l')*[A-ZÀ-ÖØ-Þ][\w'’.\-]*"
    r"(?:[ \t](?:" + _EU_CONNECTOR + r"[ \t]+|d'|l')*[A-ZÀ-ÖØ-Þ][\w'’.\-]*){0,3}"
)
_HOUSE_NO = (
    r"\d{1,4}(?:[ \t]?(?:bis|ter|[a-zA-Z]))?(?![\w])"
    r"(?:[ \t]?[/-][ \t]?(?:\d{1,4}[a-zA-Z]?|[A-Z](?![\w])))*"
)
_STREET_EU_NUMBER_FIRST = (
    r"(?<![\w.])(?P<v>\d{1,4}(?:[ \t]?(?:bis|ter|[a-zA-Z]))?,?[ \t]+(?:"
    + _EU_STREET_WORDS
    + r"|"
    + _EU_LOWER_WORDS
    + r")[ \t]+"
    + _EU_NAME
    + r")"
)
_STREET_EU_NAME_FIRST = (
    r"(?<![\w])(?P<v>" + _EU_STREET_WORDS + r"[ \t]+" + _EU_NAME + r",?[ \t]+" + _HOUSE_NO + r")"
)
_STREET_NL = (
    r"(?<![\w])(?P<v>[A-Z][a-zà-ÿ\-]+(?:straat|laan|weg|gracht|plein|kade|singel|dijk|steeg|"
    r"markt)[ \t]+" + _HOUSE_NO + r")"
)
# Knowingly not covered: a bare first name in unlabelled prose ("my son Noah"), when the
# English NER model misses it (and in German text, where single-word NER names are ignored),
# and street names written without a house number.
_ADDRESS_RES = [
    re.compile(p)
    for p in (
        _STREET_EN,
        _STREET_DE,
        _STREET_EU_NUMBER_FIRST,
        _STREET_EU_NAME_FIRST,
        _STREET_NL,
        _POSTAL_CITY,
        _US_CITY_ZIP,
        _PO_BOX,
    )
]
_PHONE_LABELED = re.compile(
    r"(?i:tel(?:efon)?\.?|phone|mobile|mobil|handy|fax|cell)\s*[:.]?\s*"
    r"(?P<v>\+?\(?\d[\d\s()/.-]{5,}\d)"
)

# Medical content that must never be redacted.
_PROTECTED_RE = re.compile(
    r"\b(?:NM|NC|NG|NP|NR|XM|ENST|ENSG|LRG)_\d+(?:\.\d+)?(?::[cgmnpr]\.[^\s,;)]+)?"
    r"|\b[cgmnpr]\.(?:\(?[A-Za-z*]*-?\d+[^\s,;]*)"
    r"|\b(?:HP|MONDO|OMIM|MIM|ORPHA|HGNC|DOID|GO|CHEBI|PMID|PMCID|MESH)[:_ ]?\s?\d+"
    r"|\bNCT\d{8}\b|\bVCV\d+|\bRCV\d+|\brs\d{3,}\b|\bchr(?:\d{1,2}|[XYM])[:\d,._-]*"
    r"|\b\d+(?:[.,]\d+)?\s?(?:years?|yrs?|months?|weeks?|days?|Jahre?n?|Monate?n?|Wochen?|Tage?n?)"
    r"(?:\s?(?:old|alt))?\b",
)
_PLAIN_DATE_RE = re.compile(r"(?<![\w.])" + _DATE + r"(?![\w])")
_GENE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}\d[A-Z0-9]{0,4}(?:-[A-Z0-9]+)?$|^[A-Z0-9]{2,8}-AS\d$")
_KNOWN_GENES = {
    "ARX",
    "DMD",
    "CFTR",
    "HTT",
    "PAH",
    "PTEN",
    "ATM",
    "RET",
    "KIT",
    "APC",
    "VHL",
    "GBA",
    "DCX",
    "LIS",
    "POLG",
    "NPC",
    "HEXA",
    "HEXB",
    "IDS",
    "IDUA",
    "GAA",
    "GLA",
    "ASPA",
    "GALC",
    "ATP",
    "SMN",
    "TTN",
    "MYH",
    "LMNA",
    "FBN",
    "PKD",
    "BRCA",
    "MECP",
    "SYNGAP",
    "GRIN",
    "KCNQ",
}
_STRONG_EPONYMS = {
    "dravet",
    "ohtahara",
    "rett",
    "lennox",
    "gastaut",
    "lennox-gastaut",
    "angelman",
    "prader",
    "willi",
    "prader-willi",
    "doose",
    "landau",
    "kleffner",
    "landau-kleffner",
    "aicardi",
    "goutières",
    "goutieres",
    "sturge",
    "sturge-weber",
    "tay",
    "sachs",
    "tay-sachs",
    "batten",
    "niemann",
    "niemann-pick",
    "gaucher",
    "fabry",
    "pompe",
    "huntington",
    "duchenne",
    "marfan",
    "ehlers",
    "danlos",
    "ehlers-danlos",
    "noonan",
    "patau",
    "kabuki",
    "sotos",
    "smith-magenis",
    "magenis",
    "lemli",
    "opitz",
    "smith-lemli-opitz",
    "canavan",
    "krabbe",
    "menkes",
    "alpers",
    "kearns",
    "sayre",
    "kearns-sayre",
    "wolf-hirschhorn",
    "hirschhorn",
    "phelan-mcdermid",
    "mcdermid",
    "pitt-hopkins",
    "coffin-siris",
    "jeavons",
    "tourette",
    "asperger",
    "crohn",
    "hodgkin",
    "parkinson",
    "alzheimer",
    "charcot",
    "charcot-marie-tooth",
    "friedreich",
    "stargardt",
    "leber",
    "alport",
    "bartter",
    "gitelman",
    "hurler",
    "sanfilippo",
    "morquio",
    "wolfram",
    "joubert",
    "dandy-walker",
    "rubinstein-taybi",
    "taybi",
    "cockayne",
    "fanconi",
    "gorlin",
    "cowden",
    "li-fraumeni",
    "fraumeni",
    "hippel",
    "lindau",
    "von hippel-lindau",
    "zellweger",
    "refsum",
    "menière",
    "ménière",
    "meniere",
    "kawasaki",
    "behçet",
    "behcet",
    "sjögren",
    "sjogren",
    "guillain-barré",
    "guillain",
    "barré",
    "barre",
    "rasmussen",
    "panayiotopoulos",
    "unverricht",
    "lundborg",
    "unverricht-lundborg",
    "lafora",
    "sandhoff",
    "bielschowsky",
    "jansky-bielschowsky",
    "spielmeyer-vogt",
    "christianson",
    "mowat-wilson",
    "kleefstra",
    "koolen-de vries",
    "schinzel-giedion",
    "holt-oram",
    "digeorge",
    "treacher",
    "apert",
    "crouzon",
    "pfeiffer",
    "hirschsprung",
    "beckwith-wiedemann",
    "wiedemann",
    "silver-russell",
    "cushing",
    "addison",
    "hashimoto",
    "cornelia de lange",
    "de lange",
    "west",
    "dup15q",
    "dandy",
    "walker",
    "rubinstein",
    "lowe",
    "alexander",
    "wilson",
    "leigh",
    "usher",
    "lesch-nyhan",
    "nyhan",
    "lesch",
    "möbius",
    "moebius",
    "aarskog",
    "allan-herndon-dudley",
    "dyggve",
    "melchior",
    "clausen",
    "cohen",
    "costello",
    "kleine-levin",
}
_DISEASE_WORDS = re.compile(
    r"(?i)\b(?:syndrome|syndrom|disease|disorder|encephalopathy|epilepsy|dystrophy|palsy|sign|"
    r"anomaly|type|krankheit|erkrankung|ataxia|ataxie|neuropathy|myopathy|leukodystrophy|"
    r"deficiency|spectrum|like|plus|variant|malformation|complex|sequence|anomalie|"
    r"ähnliche[rsn]?|artige[rsn]?|symptomatik|phenotype|phänotyp|kranke?)\b"
)
_ALWAYS_ALLOWED = {"dr. wu", "wu", "henry wu", "dr. henry wu", "amber", "chatgpt", "openai"}
_COUNTRIES = {
    "austria",
    "österreich",
    "germany",
    "deutschland",
    "switzerland",
    "schweiz",
    "france",
    "italy",
    "spain",
    "portugal",
    "netherlands",
    "belgium",
    "luxembourg",
    "denmark",
    "sweden",
    "norway",
    "finland",
    "iceland",
    "ireland",
    "united kingdom",
    "uk",
    "england",
    "scotland",
    "wales",
    "poland",
    "czech republic",
    "czechia",
    "slovakia",
    "hungary",
    "slovenia",
    "croatia",
    "serbia",
    "romania",
    "bulgaria",
    "greece",
    "turkey",
    "ukraine",
    "russia",
    "estonia",
    "latvia",
    "lithuania",
    "united states",
    "usa",
    "us",
    "u.s.",
    "america",
    "canada",
    "mexico",
    "brazil",
    "argentina",
    "chile",
    "colombia",
    "peru",
    "australia",
    "new zealand",
    "japan",
    "china",
    "india",
    "south korea",
    "korea",
    "israel",
    "egypt",
    "south africa",
    "nigeria",
    "kenya",
    "europe",
    "eu",
    "the united states",
    "the netherlands",
    "the uk",
    "italien",
    "frankreich",
    "spanien",
    "niederlande",
    "belgien",
    "polen",
    "ungarn",
    "tschechien",
}


@dataclass(frozen=True)
class RedactedSpan:
    start: int
    end: int
    entity_type: str
    placeholder: str
    redacted_start: int
    redacted_end: int


@dataclass
class RedactionResult:
    text: str
    spans: list[RedactedSpan] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.spans)

    def entity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.spans:
            counts[s.entity_type] = counts.get(s.entity_type, 0) + 1
        return counts

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Map a [start, end) range in the redacted text to the original text."""
        return self._map_offset(start, False), self._map_offset(end, True)

    def _map_offset(self, pos: int, is_end: bool) -> int:
        shift = 0
        for s in self.spans:
            if pos <= s.redacted_start:
                break
            if pos < s.redacted_end:
                return s.end if is_end else s.start
            shift = s.end - s.redacted_end
        return pos + shift


class _RegexGroupRecognizer(EntityRecognizer):
    """Regex recognizer that reports only the named group `v` (so labels stay in the text)."""

    def __init__(self, name: str, entity: str, patterns: list[re.Pattern], score: float = 0.9):
        self._patterns = patterns
        self._score = score
        super().__init__(supported_entities=[entity], name=name, supported_language="en")

    def load(self) -> None:
        pass

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        out = []
        for pattern in self._patterns:
            for m in pattern.finditer(text):
                start, end = m.span("v")
                value = m.group("v").rstrip(" ,.;:")
                end = start + len(value)
                if end > start:
                    out.append(
                        RecognizerResult(
                            self.supported_entities[0],
                            start,
                            end,
                            self._score,
                            recognition_metadata={
                                RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                                _LABELED: True,
                            },
                        )
                    )
        return out


class Redactor:
    def __init__(self, *, score_threshold: float = 0.4):
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
            }
        )
        nlp_engine = provider.create_engine()
        registry = RecognizerRegistry(supported_languages=["en"])
        for recognizer in (
            SpacyRecognizer(supported_entities=["PERSON", "LOCATION"]),
            EmailRecognizer(),
            PhoneRecognizer(supported_regions=("US", "UK", "DE", "AT", "CH", "FR", "IT", "CA")),
            UsSsnRecognizer(),
            IbanRecognizer(),
            CreditCardRecognizer(),
            IpRecognizer(),
            _RegexGroupRecognizer("dob", "DATE_OF_BIRTH", [_DOB_RE], 0.95),
            _RegexGroupRecognizer("labeled_name", "PERSON", _NAME_RES, 0.9),
            _RegexGroupRecognizer("labeled_id", "PATIENT_ID", [_ID_RE], 0.9),
            _RegexGroupRecognizer("svnr", "PATIENT_ID", [_SVNR_RE], 0.6),
            _RegexGroupRecognizer("address", "STREET_ADDRESS", _ADDRESS_RES, 0.85),
            _RegexGroupRecognizer("labeled_phone", "PHONE_NUMBER", [_PHONE_LABELED], 0.9),
        ):
            registry.add_recognizer(recognizer)
        self.analyzer = AnalyzerEngine(
            registry=registry, nlp_engine=nlp_engine, supported_languages=["en"]
        )
        self.score_threshold = score_threshold

    def redact(self, text: str, *, allow_terms: Iterable[str] = ()) -> RedactionResult:
        if not text or not text.strip():
            return RedactionResult(text=text)
        allow = {t.strip().lower() for t in allow_terms if t and t.strip()} | _ALWAYS_ALLOWED
        results = self.analyzer.analyze(
            text=text, language="en", entities=ENTITIES, score_threshold=self.score_threshold
        )
        protected = [m.span() for m in _PROTECTED_RE.finditer(text)]
        protected += [m.span() for m in _PLAIN_DATE_RE.finditer(text)]
        german = _looks_german(text)
        results = [_trim_to_line(r, text) for r in results]
        kept = [r for r in results if self._keep(r, text, allow, protected, german)]
        return _apply(text, _resolve_overlaps(kept))

    def _keep(
        self,
        r: RecognizerResult,
        text: str,
        allow: set[str],
        protected: list[tuple[int, int]],
        german: bool = False,
    ) -> bool:
        value = text[r.start : r.end].strip()
        lowered = value.lower().strip(" .,;:'\"()")
        if lowered in allow:
            return False
        labeled = bool((r.recognition_metadata or {}).get(_LABELED))
        if r.entity_type in ("PERSON", "LOCATION") and not labeled:
            if lowered in _COUNTRIES:
                return False
            if any(_is_gene(tok) for tok in value.split()):
                return False
            if _is_medical_eponym(text, r.start, r.end, value):
                return False
            tokens = [t.lower() for t in re.split(r"[\s,]+", value) if t]
            if tokens and all(t in allow for t in tokens):
                return False
            # The English NER model tags capitalised German nouns as names/places; in German text
            # only multi-token names count (labelled names and addresses are caught by regex).
            if german and (r.entity_type == "LOCATION" or len(tokens) < 2):
                return False
            if len(tokens) == 1 and tokens[0].strip(".:,") in _NOT_NAMES:
                return False
        if not labeled or r.entity_type == "PHONE_NUMBER":
            for ps, pe in protected:
                if r.start < pe and ps < r.end:
                    return False
        return True


_GERMAN_WORDS = re.compile(
    r"\b(?:der|die|das|und|ist|mit|eine?[mnrs]?|nicht|bei|im|unser|unsere|geboren|sehr|geehrte|"
    r"wurde|haben|hat|auf|für|von|zu|sich|kein|keine|befund\w*|\w*befund|diagnose|patientin|"
    r"ergebnis|variante|vereinbar|geburtsdatum|einsender\w*|\w*nummer|syndrom|nachweis|"
    r"heterozygote[nr]?|homozygote[nr]?|unauffällig|ohne)\b",
    re.IGNORECASE,
)


def _looks_german(text: str) -> bool:
    return len(_GERMAN_WORDS.findall(text)) >= 3


_NOT_NAMES = {
    "email",
    "e-mail",
    "mail",
    "phone",
    "call",
    "tel",
    "fax",
    "dear",
    "hi",
    "hello",
    "mobile",
    "address",
    "dob",
    "mrn",
    "patient",
    "report",
    "result",
    "results",
    "diagnosis",
    "summary",
    "findings",
    "impression",
    "variant",
    "gene",
    "mother",
    "father",
    "son",
    "daughter",
    "doctor",
    "physician",
    "note",
    "notes",
    "thanks",
    "regards",
    "best",
    "sincerely",
    "date",
    "name",
    "indirizzo",
    "adresse",
    "dirección",
    "endereço",
    "adres",
}


def _trim_to_line(r: RecognizerResult, text: str) -> RecognizerResult:
    """NER spans sometimes run across a line break into the next label ("Michael\nDOB")."""
    value = text[r.start : r.end]
    if "\n" not in value or (r.recognition_metadata or {}).get(_LABELED):
        return r
    head = value.split("\n", 1)[0].rstrip()
    if head.strip():
        return RecognizerResult(
            r.entity_type,
            r.start,
            r.start + len(head),
            r.score,
            recognition_metadata=r.recognition_metadata,
        )
    offset = len(value) - len(value.lstrip())
    tail = value.lstrip().split("\n", 1)[0].rstrip()
    return RecognizerResult(
        r.entity_type,
        r.start + offset,
        r.start + offset + len(tail),
        r.score,
        recognition_metadata=r.recognition_metadata,
    )


def _is_gene(value: str) -> bool:
    tokens = value.split()
    return len(tokens) == 1 and (bool(_GENE_RE.match(value)) or value in _KNOWN_GENES)


_WEAK_EPONYMS = {
    "west",
    "wilson",
    "alexander",
    "leigh",
    "usher",
    "lowe",
    "cohen",
    "walker",
    "dandy",
    "addison",
    "cushing",
    "pfeiffer",
    "apert",
    "barre",
    "landau",
    "tay",
    "huntington",
    "parkinson",
    "turner",
    "down",
    "williams",
    "smith",
    "becker",
    "graves",
    "kennedy",
}


def _is_eponym_name(name: str) -> bool:
    if name in _STRONG_EPONYMS and name not in _WEAK_EPONYMS:
        return True
    return "-" in name and all(p in _STRONG_EPONYMS for p in name.split("-"))


def _is_medical_eponym(text: str, start: int, end: int, value: str) -> bool:
    """PERSON/LOCATION spans that are really eponymous disease names ("Dravet syndrome")."""
    tokens = [t for t in re.split(r"[\s,/-]+", value) if t]
    names = [t.lower().strip(".'’") for t in tokens if not _DISEASE_WORDS.fullmatch(t)]
    if not names:
        return True
    for word, nxt in zip(tokens, tokens[1:], strict=False):
        if _is_eponym_name(word.lower().strip(".'’")) and _DISEASE_WORDS.fullmatch(nxt):
            return True
    if not all(_is_eponym_name(n) or n in _WEAK_EPONYMS for n in names):
        return False
    if _DISEASE_WORDS.search(value):
        return True
    following = re.findall(r"[\w-]+", text[end : end + 60])[:3]
    if any(_DISEASE_WORDS.fullmatch(w) for w in following):
        return True
    return not any(n in _WEAK_EPONYMS for n in names)


def _resolve_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    ordered = sorted(results, key=lambda r: (r.start, -(r.end - r.start), -r.score))
    merged: list[RecognizerResult] = []
    for r in ordered:
        if merged and r.start < merged[-1].end:
            last = merged[-1]
            if r.end > last.end:
                keep_type = last.entity_type if last.score >= r.score else r.entity_type
                merged[-1] = RecognizerResult(
                    keep_type, last.start, r.end, max(last.score, r.score)
                )
            continue
        merged.append(r)
    return merged


def _apply(text: str, results: list[RecognizerResult]) -> RedactionResult:
    parts: list[str] = []
    spans: list[RedactedSpan] = []
    cursor = 0
    out_len = 0
    for r in results:
        parts.append(text[cursor : r.start])
        out_len += r.start - cursor
        placeholder = PLACEHOLDERS.get(r.entity_type, f"<{r.entity_type}>")
        spans.append(
            RedactedSpan(
                r.start, r.end, r.entity_type, placeholder, out_len, out_len + len(placeholder)
            )
        )
        parts.append(placeholder)
        out_len += len(placeholder)
        cursor = r.end
    parts.append(text[cursor:])
    return RedactionResult(text="".join(parts), spans=spans)


_redactor: Redactor | None = None
_lock = threading.Lock()


def get_redactor() -> Redactor:
    """Lazy singleton; the first call loads the spaCy model (a few seconds)."""
    global _redactor
    if _redactor is None:
        with _lock:
            if _redactor is None:
                _redactor = Redactor()
    return _redactor


def redact(text: str, *, allow_terms: Iterable[str] = ()) -> RedactionResult:
    return get_redactor().redact(text, allow_terms=allow_terms)
