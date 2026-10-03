from typing import Literal

from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import EdgeStatus, Origin, PathFamily, Relation


class GapSearchRequest(ApiModel):
    from_id: str = Field(description="Node ID at one end of the missing link.")
    to_id: str = Field(description="Node ID at the other end.")
    family: PathFamily = Field(PathFamily.all, description="Edge family of the failed path.")


class CandidateEdge(ApiModel):
    """A candidate edge found by the gap-search agent. Never promoted automatically."""

    source_id: str
    target_id: str
    relation: Relation
    quote: str = Field(description="Exact supporting span from the source.")
    source_url: str = Field(description="Where the quote was found.")
    source_type: str = Field(description="pubmed, clinicaltrials or web.")
    source_id_ref: str | None = Field(None, description="Source identifier (PMID, NCT ...).")
    origin: Origin = Field(Origin.inferred)
    status: Literal[EdgeStatus.pending_review] = Field(
        EdgeStatus.pending_review, description="Always pending_review."
    )
