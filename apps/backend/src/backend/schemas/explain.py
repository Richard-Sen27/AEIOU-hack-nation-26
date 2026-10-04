from pydantic import Field

from backend.schemas.common import LANGUAGE_PATTERN, ApiModel
from backend.schemas.enums import Role


class ExplainRequest(ApiModel):
    edge_ids: list[str] = Field(
        min_length=1, max_length=20, description="Path edges in traversal order."
    )
    role: Role | None = Field(None, description="Lens role; defaults to the user's role.")
    language: str | None = Field(
        None, pattern=LANGUAGE_PATTERN, description="Output language; defaults to the profile."
    )
    subject_node_id: str | None = Field(
        None, max_length=200, description="Summarise how this node is connected via the edges."
    )
    steps: bool = Field(
        False,
        description="Also stream `status` events while a new text is written (reading, "
        "writing, checking). Off by default, so the stream is delta..., final as before.",
    )
