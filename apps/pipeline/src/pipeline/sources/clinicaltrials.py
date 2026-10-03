"""ClinicalTrials.gov (REST API v2): studies by in-scope condition and gene terms.

Trials link to diseases only through a confident match of their listed conditions. Officials and
site principal investigators become doctor nodes with name, affiliation and trial listings only:
contact e-mails and phone numbers are removed before anything is written to disk. Observational
patient registries and natural-history studies also surface as registry nodes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.contracts import Scope, Source, assertion, raw_record, record_raw, write_tables
from pipeline.extract.common import (
    ScopeMatcher,
    disease_query_terms,
    doctor_id,
    institution_id,
    json_attrs,
    person_name_key,
    request,
)
from pipeline.http import get_client
from pipeline.paths import RAW

log = logging.getLogger(__name__)

NAME = "clinicaltrials"
API = "https://clinicaltrials.gov/api/v2/studies"


class TrialsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLINICALTRIALS_", extra="ignore")

    max_per_seed_gene: int = 50
    max_per_gene: int = 10
    max_per_seed_disease: int = 100
    max_per_disease: int = 10


cfg = TrialsSettings()

INVESTIGATOR_ROLES = {"PRINCIPAL_INVESTIGATOR", "SUB_INVESTIGATOR"}
_CONTACT_KEYS = {"phone", "phoneExt", "email"}
_NOT_A_PERSON = re.compile(
    r"\b(director|medical|clinical|trial|trials|study|studies|monitor|call|center|centre|"
    r"inc|ltd|llc|gmbh|pharma\w*|therapeutics|sponsor|department|hospital|team|office|"
    r"information|contact|support|transparency|disclosure|global|program)\b",
    re.I,
)
_GENERIC_SITE = re.compile(r"\b(research site|investigat\w* site|site \d+|clinical site)\b", re.I)
_DEGREES = re.compile(
    r"\b(m\.?d|ph\.?d|m\.?sc?|b\.?sc?|mph|mbbs|frcp\w*|dr|prof|professor|do|rn|pharmd|mba)\b\.?",
    re.I,
)


def _scrub(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _CONTACT_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def scrub_study(study: dict[str, Any]) -> dict[str, Any]:
    """Drop central contacts, non-investigator site contacts, all phones/e-mails and the large
    derived section."""
    study = dict(study)
    study.pop("derivedSection", None)
    ps = study.get("protocolSection", {})
    cl = ps.get("contactsLocationsModule")
    if cl:
        cl.pop("centralContacts", None)
        for loc in cl.get("locations", []):
            loc["contacts"] = [
                {"name": c.get("name"), "role": c.get("role")}
                for c in loc.get("contacts", [])
                if c.get("role") in INVESTIGATOR_ROLES and c.get("name")
            ]
    return _scrub(study)


def _searches(scope: Scope) -> list[dict[str, Any]]:
    out = []
    for g in scope.genes:
        cap = cfg.max_per_seed_gene if g.get("seed") else cfg.max_per_gene
        out.append(
            {"target_id": g["hgnc_id"], "param": "query.term", "value": g["symbol"], "cap": cap}
        )
    for d in scope.diseases:
        terms = disease_query_terms(scope, d)
        if not terms:
            continue
        cap = cfg.max_per_seed_disease if d.get("seed") else cfg.max_per_disease
        value = " OR ".join(f'"{t}"' for t in terms)
        out.append({"target_id": d["mondo_id"], "param": "query.cond", "value": value, "cap": cap})
    return out


async def fetch(scope: Scope | None) -> None:
    if scope is None:
        log.warning("clinicaltrials: no scope; nothing to fetch")
        return
    out = RAW / NAME
    out.mkdir(parents=True, exist_ok=True)
    studies: dict[str, dict[str, Any]] = {}
    searches = _searches(scope)
    async with get_client(NAME) as client:
        for s in searches:
            ids: list[str] = []
            token = None
            while len(ids) < s["cap"]:
                params = {
                    s["param"]: s["value"],
                    "pageSize": str(min(100, s["cap"])),
                    "format": "json",
                }
                if token:
                    params["pageToken"] = token
                r = await request(client, "GET", API, params=params, pace=0.2)
                data = r.json()
                for st in data.get("studies", []):
                    nct = st["protocolSection"]["identificationModule"]["nctId"]
                    studies[nct] = scrub_study(st)
                    ids.append(nct)
                token = data.get("nextPageToken")
                if not token:
                    break
            s["nct_ids"] = ids[: s["cap"]]
    (out / "studies.json").write_text(json.dumps(studies, ensure_ascii=False))
    (out / "searches.json").write_text(json.dumps(searches, indent=1))
    version = r.headers.get("x-api-version") if searches else None
    record_raw(NAME, API, out / "studies.json", version, studies=len(studies))
    record_raw(NAME, API, out / "searches.json", version)
    log.info("clinicaltrials: %d searches, %d unique studies", len(searches), len(studies))


def person_name(raw: str | None) -> tuple[str, str, str] | None:
    """(display name, last, first) from "Jane Q. Doe, MD, PhD" or None if not a person."""
    if not raw or _NOT_A_PERSON.search(raw):
        return None
    name = raw.split(",")[0]
    name = _DEGREES.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    toks = name.split()
    if len(toks) < 2 or any(len(re.sub(r"\W", "", t)) == 0 for t in toks):
        return None
    return name, toks[-1], toks[0]


def registry_kind(ps: dict[str, Any]) -> str | None:
    design = ps.get("designModule", {})
    if design.get("studyType") != "OBSERVATIONAL":
        return None
    if design.get("patientRegistry"):
        return "registry"
    ident = ps.get("identificationModule", {})
    text = " ".join(
        [
            ident.get("briefTitle", ""),
            ident.get("officialTitle", ""),
            *ps.get("conditionsModule", {}).get("keywords", []),
        ]
    )
    return "natural_history_study" if re.search(r"natural history", text, re.I) else None


def _trial_attrs(ps: dict[str, Any]) -> str:
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    elig = ps.get("eligibilityModule", {})
    spons = ps.get("sponsorCollaboratorsModule", {})
    locs = ps.get("contactsLocationsModule", {}).get("locations", [])
    info = design.get("designInfo", {})
    criteria = elig.get("eligibilityCriteria") or ""
    return json_attrs(
        status=status.get("overallStatus"),
        phases=design.get("phases"),
        study_type=design.get("studyType"),
        patient_registry=design.get("patientRegistry"),
        design={k: v for k, v in info.items() if isinstance(v, str)} or None,
        enrollment=design.get("enrollmentInfo", {}).get("count"),
        start_date=status.get("startDateStruct", {}).get("date"),
        completion_date=status.get("completionDateStruct", {}).get("date"),
        conditions=ps.get("conditionsModule", {}).get("conditions"),
        interventions=[
            i.get("name") for i in ps.get("armsInterventionsModule", {}).get("interventions", [])
        ],
        eligibility={
            "sex": elig.get("sex"),
            "min_age": elig.get("minimumAge"),
            "max_age": elig.get("maximumAge"),
            "std_ages": elig.get("stdAges"),
            "healthy_volunteers": elig.get("healthyVolunteers"),
            "summary": criteria[:600] + ("…" if len(criteria) > 600 else ""),
        },
        lead_sponsor=spons.get("leadSponsor", {}).get("name"),
        collaborators=[c.get("name") for c in spons.get("collaborators", [])],
        countries=sorted({loc.get("country") for loc in locs if loc.get("country")}),
        n_locations=len(locs),
    )


def normalize(scope: Scope) -> None:
    raw = RAW / NAME
    if not (raw / "studies.json").exists():
        log.warning("clinicaltrials: no raw data; writing empty tables")
        write_tables(NAME)
        return
    studies = json.loads((raw / "studies.json").read_text())
    ts = (raw_record(NAME, "studies.json") or {}).get("retrieved_at")
    matcher = ScopeMatcher(scope)
    nodes: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    synonyms: list[dict[str, Any]] = []
    doctors: dict[str, dict[str, Any]] = {}
    dropped = 0

    def institution(name: str, **attrs) -> str:
        iid = institution_id(name)
        nodes.setdefault(
            iid,
            {
                "id": iid,
                "type": "institution",
                "label": name,
                "description": None,
                "url": None,
                "attrs": json_attrs(source=NAME, **attrs),
            },
        )
        return iid

    def doctor(raw_name: str, nct: str, url: str, role: str, affiliation: str | None):
        parsed = person_name(raw_name)
        if not parsed:
            return None
        display, last, first = parsed
        key, _ = person_name_key(last, first)
        did = doctor_id(key)
        d = doctors.setdefault(
            did,
            {
                "name": display,
                "name_key": key,
                "affiliations": set(),
                "roles": set(),
                "trials": set(),
            },
        )
        d["roles"].add(role)
        d["trials"].add(nct)
        rows.append(
            assertion(
                did,
                nct,
                "investigator_of",
                tier="curated_db",
                source_type=NAME,
                source_ref=nct,
                url=url,
                retrieved_at=ts,
                features={"role": role},
            )
        )
        if affiliation and not _GENERIC_SITE.search(affiliation):
            d["affiliations"].add(affiliation)
            iid = institution(affiliation)
            rows.append(
                assertion(
                    did,
                    iid,
                    "affiliated_with",
                    tier="curated_db",
                    source_type=NAME,
                    source_ref=nct,
                    url=url,
                    retrieved_at=ts,
                    quote=affiliation,
                )
            )
        return did

    for nct, st in studies.items():
        ps = st.get("protocolSection", {})
        conditions = ps.get("conditionsModule", {}).get("conditions", [])
        matches = {}
        for cond in conditions:
            for m in matcher.diseases_in(cond):
                matches.setdefault(m.node_id, (cond, m))
        if not matches:
            dropped += 1
            continue
        ident = ps.get("identificationModule", {})
        url = f"https://clinicaltrials.gov/study/{nct}"
        summary = ps.get("descriptionModule", {}).get("briefSummary") or ""
        nodes[nct] = {
            "id": nct,
            "type": "trial",
            "label": ident.get("briefTitle") or nct,
            "description": summary[:500] + ("…" if len(summary) > 500 else ""),
            "url": url,
            "attrs": _trial_attrs(ps),
        }
        if ident.get("acronym"):
            synonyms.append({"node_id": nct, "synonym": ident["acronym"], "source": NAME})
        for disease_id, (cond, m) in matches.items():
            rows.append(
                assertion(
                    nct,
                    disease_id,
                    "studies",
                    tier="curated_db",
                    source_type=NAME,
                    source_ref=nct,
                    url=url,
                    quote=cond,
                    retrieved_at=ts,
                    features={"match": m.method, "term": m.term},
                )
            )
        cl = ps.get("contactsLocationsModule", {})
        for off in cl.get("overallOfficials", []):
            doctor(off.get("name"), nct, url, off.get("role") or "OFFICIAL", off.get("affiliation"))
        for loc in cl.get("locations", []):
            for c in loc.get("contacts", []):
                doctor(c.get("name"), nct, url, c.get("role"), loc.get("facility"))

        kind = registry_kind(ps)
        if kind:
            rid = f"REG:{nct.lower()}"
            nodes[rid] = {
                "id": rid,
                "type": "registry",
                "label": ident.get("acronym") or ident.get("briefTitle") or nct,
                "description": ident.get("officialTitle") or ident.get("briefTitle"),
                "url": url,
                "attrs": json_attrs(kind=kind, nct_id=nct, source=NAME),
            }
            for disease_id, (cond, m) in matches.items():
                rows.append(
                    assertion(
                        rid,
                        disease_id,
                        "studies",
                        tier="curated_db",
                        source_type=NAME,
                        source_ref=nct,
                        url=url,
                        quote=cond,
                        retrieved_at=ts,
                        features={"match": m.method},
                    )
                )
            sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
            if sponsor.get("name"):
                iid = institution(sponsor["name"], sponsor_class=sponsor.get("class"))
                rows.append(
                    assertion(
                        iid,
                        rid,
                        "runs",
                        tier="curated_db",
                        source_type=NAME,
                        source_ref=nct,
                        url=url,
                        retrieved_at=ts,
                        quote=sponsor["name"],
                    )
                )

    for did, d in doctors.items():
        nodes[did] = {
            "id": did,
            "type": "doctor",
            "label": d["name"],
            "description": None,
            "url": None,
            "attrs": json_attrs(
                name_key=d["name_key"],
                affiliations=sorted(d["affiliations"]),
                trial_roles=sorted(d["roles"]),
                n_trials=len(d["trials"]),
                source=NAME,
            ),
        }
        synonyms.append({"node_id": did, "synonym": d["name"], "source": NAME})
    write_tables(NAME, list(nodes.values()), synonyms, _dedupe(rows))
    log.info(
        "clinicaltrials: %d trials kept, %d without an in-scope condition",
        sum(1 for n in nodes.values() if n["type"] == "trial"),
        dropped,
    )


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for r in rows:
        k = (r["source_id"], r["relation"], r["target_id"], r["source_ref"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


SOURCE = Source(NAME, "scoped", fetch, normalize)
