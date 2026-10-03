from pydantic import Field

from backend.schemas.chat import Action
from backend.schemas.common import LANGUAGE_PATTERN, ApiModel
from backend.schemas.enums import Role


class ProposalRequest(ApiModel):
    edge_ids: list[str] = Field(min_length=1, max_length=50, description="Path or action edges.")
    actions: list[Action] | None = Field(None, description="Action cards from the agent reply.")
    title: str | None = Field(None, max_length=200)
    role: Role | None = Field(None, description="Lens role; defaults to the user's role.")
    language: str | None = Field(None, pattern=LANGUAGE_PATTERN)
