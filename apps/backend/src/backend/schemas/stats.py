from pydantic import Field

from backend.schemas.common import ApiModel


class AtlasStats(ApiModel):
    """Headline counts of the loaded graph, computed once per data version."""

    data_version: str | None = Field(description="Data version the counts were computed from.")
    diseases: int = Field(description="Disease nodes in the graph.")
    genes: int = Field(description="Gene nodes in the graph.")
    symptoms: int = Field(description="Symptom (phenotype) nodes in the graph.")
    links_cited: int = Field(description="Links with origin observed (backed by a source).")
    links_computed: int = Field(description="Links with origin inferred (computed hypotheses).")
