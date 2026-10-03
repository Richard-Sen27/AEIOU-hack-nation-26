from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.enums import ErrorCode, Role

LANGUAGE_PATTERN = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$"


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


class Lens(ApiModel):
    """Presentation lens for a request. A lens never filters data."""

    role: Role = Field(Role.guest, description="Role used for presentation (start view, wording).")
    language: str = Field(
        "en", pattern=LANGUAGE_PATTERN, description="Output language, BCP 47 tag (e.g. en, de)."
    )
    expert_mode: bool = Field(
        False, description="Expert mode: mechanism queries return ranked clusters."
    )


class ErrorDetail(ApiModel):
    code: ErrorCode = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable message. Never echoes user content.")


class ErrorResponse(ApiModel):
    """The single error envelope used by every endpoint."""

    error: ErrorDetail


class Ok(ApiModel):
    ok: bool = Field(True, description="Always true.")
