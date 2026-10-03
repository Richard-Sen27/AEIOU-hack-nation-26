import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

JSON_SCHEMA_OPEN = "<json_schema>"
JSON_SCHEMA_CLOSE = "</json_schema>"
TOOLS_OPEN = "<tools>"
TOOLS_CLOSE = "</tools>"


def schema_name(model: type[BaseModel]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", model.__name__)[:64] or "output"


def strict_json_schema(model: type[BaseModel]) -> tuple[dict[str, Any], bool]:
    """Return (schema, strict). Falls back to the plain schema when strict conversion fails."""
    from agents.strict_schema import ensure_strict_json_schema

    schema = model.model_json_schema()
    try:
        return ensure_strict_json_schema(schema), True
    except Exception:
        return schema, False


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in `text` (tolerates code fences and prose around it)."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", stripped):
        try:
            value, _ = decoder.raw_decode(stripped[match.start() :])
            return value
        except ValueError:
            continue
    raise ValueError("no JSON value found")


def validation_feedback(exc: Exception) -> str:
    """Compact validation error for the model. Excludes input values."""
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)[:10]
        ]
        return "; ".join(parts)
    return "the reply was not a single valid JSON value"


def json_only_instructions(schema: dict[str, Any]) -> str:
    return (
        "\n\nRespond with ONLY one JSON object that conforms to the JSON Schema below. "
        "No prose, no markdown, no code fences.\n"
        f"{JSON_SCHEMA_OPEN}{json.dumps(schema, separators=(',', ':'))}{JSON_SCHEMA_CLOSE}"
    )


def tool_protocol_instructions(
    tools: list[dict[str, Any]], final_schema: dict[str, Any] | None
) -> str:
    final = (
        "an object conforming to the JSON Schema in <json_schema>"
        if final_schema is not None
        else "your final answer as a string"
    )
    text = (
        "\n\nYou can call tools. They are listed in <tools> as JSON (name, description, "
        "parameters as JSON Schema). Each reply must be ONLY one JSON object, no prose:\n"
        '- to call a tool: {"tool": "<name>", "arguments": {...}}\n'
        f'- to finish: {{"final": <answer>}} where <answer> is {final}.\n'
        "Call one tool per reply. Tool results come back as <tool_result> messages.\n"
        f"{TOOLS_OPEN}{json.dumps(tools, separators=(',', ':'))}{TOOLS_CLOSE}"
    )
    if final_schema is not None:
        text += f"\n{JSON_SCHEMA_OPEN}{json.dumps(final_schema, separators=(',', ':'))}"
        text += JSON_SCHEMA_CLOSE
    return text
