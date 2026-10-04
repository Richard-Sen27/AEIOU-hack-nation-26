"""Shared enums and constants for pipeline, API and frontend (stdlib only).

Node ID conventions:
    disease      MONDO:0100135
    gene         HGNC:11444
    phenotype    HP:0001250
    variant      CLINVAR:<VariationID>
    mechanism    MECH:loss_of_function | MECH:gain_of_function | MECH:dominant_negative
    pathway      REACT:R-HSA-... or GO:...
    paper        PMID:...
    claim        CLAIM:<hash>
    researcher   RES:<hash> or ORCID:...
    doctor       DOC:<hash>
    institution  INST:<hash>
    network      NET:<slug>
    grant        GRANT:<project number>
    trial        NCT...
    patient_org  ORG:<slug>
    registry     REG:<slug>  (attrs.kind = registry | natural_history_study)
    cluster      CLUSTER:<n>

Edge IDs: edge_id(source, relation, target). Path IDs: path_id(edge_ids).
"""

import hashlib
import math
from collections.abc import Iterable, Sequence
from enum import StrEnum


class NodeType(StrEnum):
    disease = "disease"
    gene = "gene"
    variant = "variant"
    mechanism = "mechanism"
    pathway = "pathway"
    phenotype = "phenotype"
    paper = "paper"
    claim = "claim"
    researcher = "researcher"
    doctor = "doctor"
    institution = "institution"
    network = "network"
    grant = "grant"
    trial = "trial"
    patient_org = "patient_org"
    registry = "registry"
    cluster = "cluster"


class Relation(StrEnum):
    caused_by_variant_in = "caused_by_variant_in"
    acts_via = "acts_via"
    participates_in = "participates_in"
    has_phenotype = "has_phenotype"
    same_gene_same_mechanism = "same_gene_same_mechanism"
    same_gene_different_mechanism = "same_gene_different_mechanism"
    shared_pathway = "shared_pathway"
    similar_symptoms = "similar_symptoms"
    shared_researcher = "shared_researcher"
    shared_gene = "shared_gene"
    near_on_chromosome = "near_on_chromosome"
    candidate_phenotype = "candidate_phenotype"
    suggested_by_neighbour = "suggested_by_neighbour"
    asserts = "asserts"
    authored = "authored"
    pi_of = "pi_of"
    funds_research_on = "funds_research_on"
    serves = "serves"
    runs = "runs"
    studies = "studies"
    investigator_of = "investigator_of"
    affiliated_with = "affiliated_with"
    variant_of = "variant_of"
    observed_in = "observed_in"
    member_of = "member_of"
    about = "about"


class EdgeFamily(StrEnum):
    dna = "dna"
    symptoms = "symptoms"
    research = "research"
    community = "community"


RELATION_FAMILY: dict[Relation, EdgeFamily] = {
    Relation.caused_by_variant_in: EdgeFamily.dna,
    Relation.acts_via: EdgeFamily.dna,
    Relation.participates_in: EdgeFamily.dna,
    Relation.variant_of: EdgeFamily.dna,
    Relation.observed_in: EdgeFamily.dna,
    Relation.same_gene_same_mechanism: EdgeFamily.dna,
    Relation.same_gene_different_mechanism: EdgeFamily.dna,
    Relation.shared_pathway: EdgeFamily.dna,
    Relation.shared_gene: EdgeFamily.dna,
    Relation.near_on_chromosome: EdgeFamily.dna,
    Relation.has_phenotype: EdgeFamily.symptoms,
    Relation.similar_symptoms: EdgeFamily.symptoms,
    Relation.candidate_phenotype: EdgeFamily.symptoms,
    Relation.suggested_by_neighbour: EdgeFamily.symptoms,
    Relation.asserts: EdgeFamily.research,
    Relation.authored: EdgeFamily.research,
    Relation.pi_of: EdgeFamily.research,
    Relation.funds_research_on: EdgeFamily.research,
    Relation.shared_researcher: EdgeFamily.research,
    Relation.about: EdgeFamily.research,
    Relation.serves: EdgeFamily.community,
    Relation.runs: EdgeFamily.community,
    Relation.studies: EdgeFamily.community,
    Relation.investigator_of: EdgeFamily.community,
    Relation.affiliated_with: EdgeFamily.community,
    Relation.member_of: EdgeFamily.community,
}

# Undirected relations (disease <-> disease, plus gene <-> gene near_on_chromosome); their edge
# IDs sort the two endpoint IDs first.
SYMMETRIC_RELATIONS: frozenset[Relation] = frozenset(
    {
        Relation.same_gene_same_mechanism,
        Relation.same_gene_different_mechanism,
        Relation.shared_pathway,
        Relation.similar_symptoms,
        Relation.shared_researcher,
        Relation.shared_gene,
        Relation.near_on_chromosome,
    }
)


class PathFamily(StrEnum):
    dna = "dna"
    symptoms = "symptoms"
    research = "research"
    all = "all"


class Origin(StrEnum):
    observed = "observed"
    inferred = "inferred"
    patient_reported = "patient_reported"
    user_contributed = "user_contributed"


class EdgeStatus(StrEnum):
    active = "active"
    pending_review = "pending_review"
    under_review = "under_review"


class EvidenceTier(StrEnum):
    curated_db = "curated_db"
    peer_reviewed = "peer_reviewed"
    review = "review"
    preprint = "preprint"
    llm_inferred = "llm_inferred"
    patient_reported = "patient_reported"
    computed = "computed"  # links inferred by the analysis (origin=inferred); a hypothesis


# computed: the ceiling for an inferred link's score-based weight (the global inferred cap, so a
# hypothesis never reaches "High"); each computed row is weighted by its link's own score.
TIER_WEIGHTS: dict[EvidenceTier, float] = {
    EvidenceTier.curated_db: 0.9,
    EvidenceTier.peer_reviewed: 0.7,
    EvidenceTier.review: 0.5,
    EvidenceTier.preprint: 0.4,
    EvidenceTier.llm_inferred: 0.3,
    EvidenceTier.patient_reported: 0.2,
    EvidenceTier.computed: 0.79,
}


class Polarity(StrEnum):
    supports = "supports"
    contradicts = "contradicts"


class ClaimType(StrEnum):
    patient_observation = "patient_observation"
    experimental = "experimental"
    review = "review"
    hypothesis = "hypothesis"


class Role(StrEnum):
    guest = "guest"
    patient = "patient"
    doctor = "doctor"
    researcher = "researcher"


class AuthProvider(StrEnum):
    """How an account signs in: openai (Sign in with ChatGPT) or google. One account per
    provider identity; accounts are never merged by e-mail."""

    openai = "openai"
    google = "google"


class ConsentType(StrEnum):
    """health_data: one consent to process the user's own health and genetic data (chat,
    profile, documents); contribute: share data with the atlas, a separate purpose."""

    health_data = "health_data"
    contribute = "contribute"


class ConfidenceLevel(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class DocType(StrEnum):
    genetic_report = "genetic_report"
    clinical_letter = "clinical_letter"
    research_paper = "research_paper"
    registry_document = "registry_document"


class VariantClassification(StrEnum):
    pathogenic = "pathogenic"
    likely_pathogenic = "likely_pathogenic"
    uncertain_significance = "uncertain_significance"
    likely_benign = "likely_benign"
    benign = "benign"


class Zygosity(StrEnum):
    heterozygous = "heterozygous"
    homozygous = "homozygous"
    hemizygous = "hemizygous"
    compound_heterozygous = "compound_heterozygous"
    mosaic = "mosaic"
    unknown = "unknown"


class DocumentStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"  # findings extracted, awaiting review
    failed = "failed"


class FindingType(StrEnum):
    disease = "disease"
    gene = "gene"
    variant = "variant"
    phenotype = "phenotype"
    candidate_edge = "candidate_edge"


class JobKind(StrEnum):
    document_extraction = "document_extraction"
    gap_search = "gap_search"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobStage(StrEnum):
    queued = "queued"
    extracting_text = "extracting_text"
    redacting = "redacting"
    classifying = "classifying"
    extracting_findings = "extracting_findings"
    done = "done"


class ContributionKind(StrEnum):
    phenotype_profile = "phenotype_profile"
    asset = "asset"
    candidate_edge = "candidate_edge"


class ContributionStatus(StrEnum):
    pending_review = "pending_review"
    accepted = "accepted"
    rejected = "rejected"


class AssetType(StrEnum):
    registry = "registry"
    natural_history_study = "natural_history_study"
    model = "model"
    biomarker = "biomarker"
    other = "other"


class FlagStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class ChipType(StrEnum):
    disease = "disease"
    gene = "gene"
    variant = "variant"
    symptom = "symptom"


class CardType(StrEnum):
    mini_graph = "mini_graph"
    patient_group = "patient_group"
    evidence = "evidence"
    open_in_atlas = "open_in_atlas"


class ActionType(StrEnum):
    reuse_asset = "reuse_asset"
    contact = "contact"
    join_trial = "join_trial"
    fund = "fund"


class ProfileSource(StrEnum):
    chat = "chat"
    document = "document"
    manual = "manual"


class AgeRange(StrEnum):
    under_1 = "0-1"
    age_1_5 = "1-5"
    age_6_12 = "6-12"
    age_13_17 = "13-17"
    age_18_39 = "18-39"
    age_40_64 = "40-64"
    age_65_plus = "65+"


class MatchKind(StrEnum):
    exact = "exact"
    trigram = "trigram"
    vector = "vector"


class PathStatus(StrEnum):
    ok = "ok"
    no_supported_route = "no_supported_route"


class StartLayout(StrEnum):
    ring = "ring"
    force = "force"
    hierarchy = "hierarchy"
    cluster = "cluster"
    tour = "tour"


class LabelStyle(StrEnum):
    plain = "plain"
    clinical = "clinical"
    technical = "technical"


class GraphExportFormat(StrEnum):
    csv = "csv"
    graphml = "graphml"


class GapStopReason(StrEnum):
    completed = "completed"
    max_steps = "max_steps"
    max_tokens = "max_tokens"
    timeout = "timeout"


class ErrorCode(StrEnum):
    bad_request = "bad_request"
    sign_in_required = "sign_in_required"
    consent_required = "consent_required"
    age_confirmation_required = "age_confirmation_required"
    forbidden = "forbidden"
    not_found = "not_found"
    conflict = "conflict"
    payload_too_large = "payload_too_large"
    unsupported_media_type = "unsupported_media_type"
    validation_error = "validation_error"
    rate_limited = "rate_limited"
    not_implemented = "not_implemented"
    upstream_error = "upstream_error"
    reauth_required = "reauth_required"
    assistant_unavailable = "assistant_unavailable"
    internal_error = "internal_error"


CONFIDENCE_THRESHOLD = 0.6
CONTRADICTION_PENALTY = 0.1
CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.5

VUS_NOTICE = "This result is uncertain. Discuss it with a genetic counselor before acting on it."


def confidence_level(confidence: float) -> ConfidenceLevel:
    if confidence >= CONFIDENCE_HIGH:
        return ConfidenceLevel.high
    if confidence >= CONFIDENCE_MEDIUM:
        return ConfidenceLevel.medium
    return ConfidenceLevel.low


def compute_confidence(supporting_weights: Iterable[float], n_contradicting: int) -> float:
    """Stage 4: 1 - prod(1 - w_i) - p * n_contradicting, clamped to 0..1."""
    remaining = math.prod(1.0 - w for w in supporting_weights)
    value = 1.0 - remaining - CONTRADICTION_PENALTY * n_contradicting
    return round(min(1.0, max(0.0, value)), 6)


def edge_id(source_id: str, relation: str, target_id: str) -> str:
    if relation in SYMMETRIC_RELATIONS:
        source_id, target_id = sorted((source_id, target_id))
    key = f"{source_id}|{relation}|{target_id}"
    return "e_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def path_id(edge_ids: Sequence[str]) -> str:
    return "p_" + hashlib.sha1(">".join(edge_ids).encode()).hexdigest()[:16]
